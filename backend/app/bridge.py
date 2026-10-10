# -*- coding: utf-8 -*-
"""净利润 -> 经营活动现金流 桥（把背离拆到科目级）。"""
from .normalize import find_period


def _n(v):
    return v if isinstance(v, (int, float)) else None


def _g(stmt, date):
    it = find_period(stmt, date)
    return it['values'] if it else {}


def _y0(dates, d):
    """同一累计期的起点：上一年末（12-31）。"""
    cand = [x for x in dates if x < d and x[5:7] == '12']
    return max(cand) if cand else None


def run(canon):
    bs, is_, cf = canon['资产负债表'], canon['利润表'], canon['现金流量表']
    cf_dates = sorted([it['date'] for it in cf], reverse=True)
    out = []
    for d in cf_dates[:4]:
        c = _g(cf, d)
        p = _g(is_, d)
        b = _g(bs, d)
        base = _y0(sorted([it['date'] for it in bs], reverse=True), d)
        b0 = _g(bs, base) if base else {}
        ocf = _n(c.get('经营活动现金流净额'))
        npf = _n(p.get('净利润'))
        if ocf is None or npf is None:
            continue
        dep = sum([( _n(c.get(k)) or 0) for k in ('固定资产折旧等', '无形资产摊销', '长期待摊费用摊销', '使用权资产摊销')])
        def delta(k):
            a, bb = _n(b.get(k)), _n(b0.get(k))
            if a is None or bb is None:
                return 0.0
            return a - bb
        d_ar = delta('应收账款') + delta('应收票据及应收账款') - delta('应收账款')
        d_ar = delta('应收账款')
        d_inv = delta('存货')
        d_pre = delta('预付款项')
        d_ap = delta('应付账款')
        d_cl = delta('合同负债')
        d_tax = delta('应交税费')
        items = [
            ('净利润', npf), ('折旧与摊销', dep),
            ('应收账款增加', -d_ar), ('存货增加', -d_inv), ('预付款项增加', -d_pre),
            ('应付账款增加', d_ap), ('合同负债增加', d_cl), ('应交税费增加', d_tax),
        ]
        explained = sum(v for _, v in items)
        other = ocf - explained
        items.append(('其他/未解释', other))
        gap = ocf - npf
        out.append({
            'period': d, 'base': base,
            '净利润': npf, '经营现金流': ocf, '差额': gap,
            'contributions': [{'item': k, 'amount': v, 'share_of_gap': (None if gap == 0 else round(v / gap * 100, 1))} for k, v in items],
            'explained_ratio': None if ocf == 0 else round(explained / ocf * 100, 1),
            'residual_ratio': None if ocf == 0 else round(abs(other) / abs(ocf) * 100, 1),
        })
    return out
