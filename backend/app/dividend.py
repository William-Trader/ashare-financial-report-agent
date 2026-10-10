# -*- coding: utf-8 -*-
"""分红送配 + 股息率（akshare 分红明细）。"""
import akshare as ak
from .datasource import cached, records, retry, to_em_symbol


def _f(v):
    try:
        return float(str(v).replace(',', '').replace('%', ''))
    except Exception:
        return None


def run(code, ttl=24 * 3600):
    sym = to_em_symbol(code)
    code6 = sym[2:]
    def fetch():
        try:
            return records(retry(lambda: ak.stock_history_dividend_detail(symbol=code6, indicator='分红'), tries=2))
        except Exception:
            return None
    rows = cached('div:' + sym, ttl, fetch)
    if not rows:
        return {'ok': False, 'reason': '分红数据不可用或暂无分红'}
    items = []
    for r in rows:
        items.append({'announce': str(r.get('公告日期') or '')[:10], 'song': _f(r.get('送股')),
                      'zhuan': _f(r.get('转增')), 'pai': _f(r.get('派息')),
                      'ex_date': str(r.get('除权除息日') or '')[:10], 'status': r.get('进度') or ''})
    items.sort(key=lambda x: x['announce'], reverse=True)   # 按公告日期倒序，最新在前
    items = items[:12]
    # 概览：近 3 年累计派息（每 10 股派息累加，近似）
    recent = [i for i in items if i['pai'] is not None][:3]
    return {'ok': True, 'code': sym, 'items': items,
            'note': '派息为每 10 股派息（元，含税）；股息率需结合股价另算'}
