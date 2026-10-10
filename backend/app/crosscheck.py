# -*- coding: utf-8 -*-
"""多路径口径一致性矩阵：跨表/跨期交叉核对 + 残差。"""
from .normalize import find_period


def _n(v):
    return v if isinstance(v, (int, float)) else None


def _g(stmt, date):
    it = find_period(stmt, date)
    return it['values'] if it else {}


def _prev_year_end(dates, d):
    cand = [x for x in dates if x < d and x[5:7] == '12']
    return max(cand) if cand else None


def run(canon):
    bs, is_, cf = canon['资产负债表'], canon['利润表'], canon['现金流量表']
    bs_dates = sorted([it['date'] for it in bs], reverse=True)
    is_dates = sorted([it['date'] for it in is_], reverse=True)
    rows = []
    for d in is_dates[:4]:
        b, p, c = _g(bs, d), _g(is_, d), _g(cf, d)
        det = []
        cash, end_cash = _n(b.get('货币资金')), _n(c.get('期末现金及现金等价物'))
        if cash is not None and end_cash is not None:
            det.append({'check': '货币资金 vs 现金流量表期末现金', 'left': cash, 'right': end_cash,
                        'diff': cash - end_cash, 'note': '差异通常来自受限资金/理财分类，需看附注'})
        base = _prev_year_end(bs_dates, d)
        if base:
            b0 = _g(bs, base)
            pe, pe0 = _n(b.get('归母权益合计')) or _n(b.get('所有者权益合计')), _n(b0.get('归母权益合计')) or _n(b0.get('所有者权益合计'))
            pnp = _n(p.get('归母净利润'))
            oci = _n(b.get('其他综合收益'))
            if None not in (pe, pe0, pnp):
                pred = pe0 + pnp
                det.append({'check': '归母权益变动 vs 期初+归母净利', 'left': pe, 'right': pred,
                            'diff': pe - pred, 'note': '残差应可由分红/其他综合收益/增发/回购解释'})
        npf_is, npf_cf = _n(p.get('净利润')), _n(c.get('净利润(现金流补充)'))
        if npf_is is not None and npf_cf is not None:
            det.append({'check': '净利润：利润表 vs 现金流量表补充', 'left': npf_is, 'right': npf_cf,
                        'diff': npf_is - npf_cf, 'note': '原则上应一致'})
        for x in det:
            x['status'] = 'pass' if abs(x['diff']) <= max(abs(x['left'] or 0), abs(x['right'] or 0), 1) * 0.005 else 'warn'
        rows.append({'period': d, 'items': det})
    return rows
