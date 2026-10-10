# -*- coding: utf-8 -*-
"""指标时序变点检测（二分分割 + 标准化均值差）。"""
import math


def _split_best(vals):
    n = len(vals)
    if n < 4:
        return None
    mu = sum(vals) / n
    sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / n) or 1e-9
    best = None
    for k in range(1, n):
        a, b = vals[:k], vals[k:]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        score = abs(mb - ma) / sd * math.sqrt(len(a) * len(b) / n)
        if best is None or score > best[0]:
            best = (score, k, ma, mb)
    if best is None:
        return None
    score, k, ma, mb = best
    return {'index': k, 'score': round(score, 2), 'before': round(ma, 2), 'after': round(mb, 2),
            'significant': score >= 1.5}


def run(ind, keys=('毛利率%', '归母净利率%', '净现比', '单季营收同比%', '单季归母净利同比%')):
    rows = ind.get('rows', [])
    chron = list(reversed(rows[:8]))  # 最近 8 期，按时间正序
    out = []
    for k in keys:
        vals = [(r['date'], r['indices'].get(k)) for r in chron]
        vals = [(d, v) for d, v in vals if isinstance(v, (int, float))]
        if len(vals) < 4:
            continue
        res = _split_best([v for _, v in vals])
        if not res:
            continue
        bp = vals[res['index']][0] if res['index'] < len(vals) else vals[-1][0]
        out.append({'metric': k, 'break_period': bp, 'before': res['before'], 'after': res['after'],
                    'score': res['score'], 'significant': res['significant']})
    return out
