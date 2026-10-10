# -*- coding: utf-8 -*-
"""截面因子库：z 分数、分位、五档分层（机构级横截面）。"""
import math
from . import warehouse, strategy

FACTORS = {'np_yoy': '净利增速', 'rev_yoy': '营收增速', 'roe': 'ROE', 'gm': '毛利率'}


def _z(xs, v):
    if not isinstance(v, (int, float)):
        return None
    mu = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs)) or 1e-9
    return max(-3.0, min(3.0, (v - mu) / sd))


def run(date=None, factor='score', buckets=5):
    d, rows = warehouse.market_snap(date)
    if not rows:
        return {'ok': False, 'reason': '仓库暂无快照'}
    _W = strategy.weights()
    stats = {}
    for k in FACTORS:
        xs = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
        if len(xs) < 2:
            stats[k] = (0.0, 1.0)
        else:
            mu = sum(xs) / len(xs)
            sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs)) or 1e-9
            stats[k] = (mu, sd)
    for r in rows:
        z = {}
        for k in FACTORS:
            v = r.get(k)
            if not isinstance(v, (int, float)):
                z[k] = None
            else:
                mu, sd = stats[k]
                z[k] = max(-3.0, min(3.0, (v - mu) / sd))
        r['z'] = {k: (None if v is None else round(v, 2)) for k, v in z.items()}
        num = sum(_W.get(k, 0.0) * (z.get(k) or 0) for k in FACTORS)
        r['score'] = round(max(0.0, min(100.0, 50 + num * 15)), 1)
    key = factor if factor in FACTORS else 'score'
    vals = sorted([r for r in rows if isinstance(r.get(key), (int, float))], key=lambda x: x[key])
    n = len(vals)
    out = []
    for i, r in enumerate(vals):
        q = min(buckets - 1, int(i / max(1, n) * buckets))
        out.append({'bucket': q + 1, 'code': r['code'], 'name': r['name'], 'board': r['board'],
                    'value': r[key], 'score': r.get('score')})
    dist = {}
    for b in range(1, buckets + 1):
        grp = [x for x in out if x['bucket'] == b]
        if grp:
            dist['Q' + str(b)] = {'n': len(grp), 'avg_score': round(sum(x['score'] or 0 for x in grp) / len(grp), 1),
                                  'sample': [x['name'] for x in grp[:5]]}
    stats = {}
    for k in FACTORS:
        zs = [r['z'].get(k) for r in rows if r.get('z', {}).get(k) is not None]
        if zs:
            stats[k] = {'mean_z': round(sum(zs) / len(zs), 3), 'std_z': round(math.sqrt(sum((x - sum(zs) / len(zs)) ** 2 for x in zs) / len(zs)), 3), 'n': len(zs)}
    wsum = sum(_W.get(k, 0.0) for k in FACTORS) or 1.0
    wtxt = ' · '.join('%s %d%%' % (FACTORS[k], round(100 * _W.get(k, 0) / wsum))
                      for k in FACTORS if _W.get(k, 0) > 0)
    return {'ok': True, 'date': d, 'total': n, 'factor': key, 'factors': FACTORS,
            'buckets': dist, 'factor_stats': stats, 'weights': _W, 'strategy': strategy.info(),
            'top': sorted(rows, key=lambda x: -(x.get('score') or 0))[:20],
            'note': 'z 分数缩尾 ±3；五档分层按所选因子排序；' + ('综合分权重：' + wtxt if wtxt else '综合分等权')}
