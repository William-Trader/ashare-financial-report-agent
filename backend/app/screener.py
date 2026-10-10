# -*- coding: utf-8 -*-
"""全市场多因子选股器（基于本地仓库快照，机构级筛选）。

性能：z 分数的均值/标准差按因子「预计算一次」，不再逐行重算（避免 O(n²)）。
权重：默认等权兜底，实际使用 strategy.py 的活跃策略权重，与因子分层/策略卡一致。
"""
import math
from . import warehouse, strategy

WEIGHTS = {'np_yoy': 0.35, 'rev_yoy': 0.25, 'roe': 0.25, 'gm': 0.15}


def _active_weights():
    w = dict(WEIGHTS)
    try:
        w.update({k: v for k, v in strategy.weights().items() if k in WEIGHTS})
    except Exception:
        pass
    return w


def run(date=None, min_np_yoy=None, min_rev_yoy=None, min_roe=None, min_gm=None, max_gm=None,
        boards=None, exclude_tags=None, require_tags=None, sort='score', limit=100, min_score=None):
    d, rows = warehouse.market_snap(date)
    if not rows:
        return {'ok': False, 'reason': '仓库暂无快照，请先在「数据仓库」执行同步'}
    W = _active_weights()
    stats = {}
    for k in W:
        xs = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
        if len(xs) < 2:
            stats[k] = (0.0, 1.0)
        else:
            mu = sum(xs) / len(xs)
            sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs)) or 1e-9
            stats[k] = (mu, sd)
    boards = [b for b in (boards or []) if b]
    ex = [t for t in (exclude_tags or []) if t]
    rq = [t for t in (require_tags or []) if t]
    out = []
    for r in rows:
        if boards and r['board'] not in boards:
            continue
        tags = r['tag'] or ''
        if ex and any(t in tags for t in ex):
            continue
        if rq and not any(t in tags for t in rq):
            continue
        if min_np_yoy is not None and (r['np_yoy'] is None or r['np_yoy'] < min_np_yoy):
            continue
        if min_rev_yoy is not None and (r['rev_yoy'] is None or r['rev_yoy'] < min_rev_yoy):
            continue
        if min_roe is not None and (r['roe'] is None or r['roe'] < min_roe):
            continue
        if min_gm is not None and (r['gm'] is None or r['gm'] < min_gm):
            continue
        if max_gm is not None and (r['gm'] is not None and r['gm'] > max_gm):
            continue
        z = {}
        for k in W:
            v = r[k]
            if not isinstance(v, (int, float)):
                z[k] = None
            else:
                mu, sd = stats[k]
                z[k] = max(-3.0, min(3.0, (v - mu) / sd))
        score = 50.0
        if any(z[k] is not None for k in W):
            num = sum(W[k] * (z[k] or 0) for k in W)
            score = round(max(0.0, min(100.0, 50 + num * 15)), 1)
        if min_score is not None and score < min_score:
            continue
        r = dict(r)
        r['score'] = score
        r['z'] = {k: (None if z[k] is None else round(z[k], 2)) for k in z}
        out.append(r)
    rev = (sort == 'asc')
    if sort in ('score', 'np_yoy', 'rev_yoy', 'roe', 'gm'):
        out.sort(key=lambda x: (x[sort] is None, x[sort] if x[sort] is not None else 0), reverse=not rev)
    else:
        out.sort(key=lambda x: -x['score'])
    return {'ok': True, 'date': d, 'total': len(rows), 'matched': len(out),
            'criteria': {'min_np_yoy': min_np_yoy, 'min_rev_yoy': min_rev_yoy, 'min_roe': min_roe,
                         'min_gm': min_gm, 'max_gm': max_gm, 'boards': boards,
                         'exclude_tags': ex, 'require_tags': rq, 'min_score': min_score},
            'weights': W, 'items': out[:max(1, min(int(limit or 100), 500))]}
