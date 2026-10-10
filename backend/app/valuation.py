# -*- coding: utf-8 -*-
"""估值分位（近似的 PE/PB 历史带）+ 股息率。"""
from . import marketdata as md
from .realtime import quote


def _pct_rank(vals, v):
    if v is None or not vals:
        return None
    less = sum(1 for x in vals if x < v)
    eq = sum(1 for x in vals if x == v)
    return round((less + 0.5 * eq) / len(vals) * 100, 1)


def run(code, n=250):
    k = md.daily(code, n)
    q = quote(code)
    if not k or not q.get('ok'):
        return {'ok': False, 'reason': '行情或K线不可用'}
    closes = [x['close'] for x in k]
    now = closes[-1] or 1.0
    scale = [c / now for c in closes]
    pe, pb = q.get('pe'), q.get('pb')
    out = {'ok': True, 'code': q.get('code'), 'name': q.get('name'), 'window': len(closes),
           'pe': pe, 'pb': pb, 'method': '以现价比例缩放近似历史 PE/PB（EPS/净资产视为不变）'}
    if pe:
        series = [pe * s for s in scale]
        out['pe_percentile'] = _pct_rank(series, pe)
        out['pe_min'] = round(min(series), 2)
        out['pe_max'] = round(max(series), 2)
    if pb:
        series = [pb * s for s in scale]
        out['pb_percentile'] = _pct_rank(series, pb)
        out['pb_min'] = round(min(series), 2)
        out['pb_max'] = round(max(series), 2)
    out['price_percentile'] = _pct_rank(closes, closes[-1])
    out['price_min'] = round(min(closes), 2)
    out['price_max'] = round(max(closes), 2)
    return out
