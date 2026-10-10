# -*- coding: utf-8 -*-
"""财报 PDF / 表格解析：pdfplumber 提取表格，按关键词归入三大报表。"""
import re

BS_KEYS = ['资产总计', '总资产', '负债合计', '所有者权益合计', '股东权益合计', '货币资金', '应收账款', '存货', '商誉']
IS_KEYS = ['营业总收入', '营业收入', '营业成本', '营业利润', '利润总额', '净利润', '归属于母公司', '基本每股收益']
CF_KEYS = ['经营活动产生的现金流量净额', '投资活动产生的现金流量净额', '筹资活动产生的现金流量净额',
           '销售商品、提供劳务收到的现金', '期末现金及现金等价物余额', '期初现金及现金等价物余额']


def _clean_num(s):
    if s is None:
        return None
    t = str(s).replace(',', '').replace('，', '').replace(' ', '').strip()
    if t in ('', '-', '—', '--', '/', '不适用'):
        return None
    neg = t.startswith('(') and t.endswith(')')
    if neg:
        t = t[1:-1]
    t = t.replace('元', '')
    m = re.match(r'^-?\d+(\.\d+)?$', t)
    if not m:
        return None
    v = float(t)
    return -v if neg else v


def _bucket(line):
    for k in BS_KEYS:
        if k in line:
            return '资产负债表'
    for k in CF_KEYS:
        if k in line:
            return '现金流量表'
    for k in IS_KEYS:
        if k in line:
            return '利润表'
    return None


def extract(path, max_pages=80):
    import pdfplumber
    result = {'资产负债表': {}, '利润表': {}, '现金流量表': {}, 'meta': {'tables': 0, 'pages': 0, 'file': path}}
    with pdfplumber.open(path) as pdf:
        result['meta']['pages'] = min(len(pdf.pages), max_pages)
        for pg in pdf.pages[:max_pages]:
            for tb in (pg.extract_tables() or []):
                result['meta']['tables'] += 1
                for row in tb:
                    cells = [c for c in (row or []) if c is not None and str(c).strip() != '']
                    if not cells:
                        continue
                    label = str(cells[0]).strip()
                    bucket = _bucket(label)
                    if not bucket:
                        continue
                    nums = [_clean_num(c) for c in cells[1:]]
                    nums = [n for n in nums if n is not None]
                    if nums:
                        result[bucket][label] = nums[0]
    return result
