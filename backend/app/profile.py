# -*- coding: utf-8 -*-
"""横截面分位：把标的放进同类池子里算相对位置（并发加速）。"""
from concurrent.futures import ThreadPoolExecutor
from . import scanner

METRICS = ['毛利率%', '归母净利率%', 'ROE(归母权益)%', '资产负债率%', '净现比',
           '单季营收同比%', '单季归母净利同比%', '收现比', '扣非占比%']


def _one(code, ttl):
    try:
        r = scanner.analyze(code, ttl, advanced=False)
        latest = r['indicators']['rows'][0] if r['indicators']['rows'] else {'date': '', 'indices': {}}
        return {'code': code, 'name': r['report']['name'], 'period': latest['date'], 'indices': latest['indices']}
    except Exception as e:
        return {'code': code, 'error': str(e)[:120]}


def _rank(vals, v, higher_better=True):
    if v is None or not vals:
        return None
    n = len(vals)
    less = sum(1 for x in vals if x < v)
    eq = sum(1 for x in vals if x == v)
    pct = (less + 0.5 * eq) / n * 100.0
    return round(pct if higher_better else 100 - pct, 1)


def run(codes, ttl=6 * 3600, workers=5):
    codes = list(dict.fromkeys([c for c in codes if c]))[:12]
    if not codes:
        return {'count': 0, 'metrics': METRICS, 'rows': []}
    with ThreadPoolExecutor(max_workers=min(workers, len(codes))) as ex:
        rows = list(ex.map(lambda c: _one(c, ttl), codes))
    good = [r for r in rows if 'indices' in r]
    for m in METRICS:
        vals = [v for v in (r['indices'].get(m) for r in good) if isinstance(v, (int, float))]
        for r in good:
            v = r['indices'].get(m)
            r.setdefault('percentile', {})[m] = _rank(vals, v if isinstance(v, (int, float)) else None,
                                                      higher_better=(m != '资产负债率%'))
    return {'count': len(good), 'metrics': METRICS, 'rows': rows}
