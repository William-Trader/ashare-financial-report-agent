# -*- coding: utf-8 -*-
"""策略优化：多期 walk-forward 因子权重优化（训练/留出分离），目标=正超额 + 胜率>50%。

诚实原则：只在训练期优化，在留出期验证；报告两段的数字，不藏过拟合。
"""
from . import lab, backtest as bt

FACT = ['np_yoy', 'rev_yoy', 'roe', 'gm']


def _z(row, k):
    v = row.get('z_' + k)
    return v if isinstance(v, (int, float)) else None


def _eval_w(cache, w, periods=None, h=10, topn=20, filt='非暴雷'):
    exs, ics, ns = [], [], 0
    for (d, hh), uni in cache.items():
        if hh != h or (periods and d not in periods):
            continue
        cand = []
        for x in uni:
            row = x['row']
            if not lab.FILTERS[filt](row):
                continue
            z = 0.0
            ok = True
            for k, wt in w.items():
                v = _z(row, k)
                if v is None:
                    ok = False
                    break
                z += wt * v
            if ok:
                cand.append((z, x['ret']))
        if len(cand) < 30:
            continue
        bench = sum(c[1] for c in cand) / len(cand)
        cand.sort(key=lambda t: -t[0])
        hold = cand[:topn]
        exs.append(sum(c[1] for c in hold) / len(hold) - bench)
        ics.append(bt._spearman([c[0] for c in cand], [c[1] for c in cand]))
        ns += len(cand)
    if not exs:
        return None
    return {'excess': sum(exs) / len(exs), 'win': sum(1 for e in exs if e > 0) / len(exs),
            'ic': (sum(ics) / len(ics) if ics else None), 'n': len(exs), 'stocks': ns}


def _norm(w):
    s = sum(w.values()) or 1.0
    return {k: round(v / s, 4) for k, v in w.items()}


def optimize(iterations=12, h=10, topn=20, filt='非暴雷'):
    cache = lab._prep()
    periods = sorted(set(d for d, _ in cache.keys()))
    if len(periods) < 4:
        return {'ok': False, 'reason': '报告期不足（需 >=4）', 'periods': periods}
    train, test = periods[:-2], periods[-2:]
    best_w = {'np_yoy': 0.35, 'rev_yoy': 0.25, 'roe': 0.25, 'gm': 0.15}
    best = _eval_w(cache, best_w, train, h, topn, filt)
    traj = []
    for it in range(1, iterations + 1):
        improved = False
        for k in FACT:
            for delta in (0.15, -0.15, 0.08, -0.08, 0.03, -0.03):
                w2 = dict(best_w)
                w2[k] = max(0.0, w2[k] + delta)
                w2 = _norm(w2)
                r = _eval_w(cache, w2, train, h, topn, filt)
                if r and best and r['excess'] > best['excess']:
                    best_w, best, improved = w2, r, True
        tr = _eval_w(cache, best_w, train, h, topn, filt)
        te = _eval_w(cache, best_w, test, h, topn, filt)
        traj.append({'迭代': it, '权重': dict(best_w),
                     '训练_超额%': round((tr or {}).get('excess', 0) * 100, 2),
                     '训练_胜率%': round((tr or {}).get('win', 0) * 100, 1),
                     '留出_超额%': round((te or {}).get('excess', 0) * 100, 2),
                     '留出_胜率%': round((te or {}).get('win', 0) * 100, 1),
                     'IC': (tr or {}).get('ic')})
        if not improved:
            break
    # 基线对照
    base = {'等权(1/4)': _norm({k: 1 for k in FACT}),
            '原综合分': {'np_yoy': 0.35, 'rev_yoy': 0.25, 'roe': 0.25, 'gm': 0.15}}
    cmp = []
    for name, w in base.items():
        tr = _eval_w(cache, w, train, h, topn, filt)
        te = _eval_w(cache, w, test, h, topn, filt)
        cmp.append({'策略': name, '训练_超额%': round((tr or {}).get('excess', 0) * 100, 2),
                    '留出_超额%': round((te or {}).get('excess', 0) * 100, 2), 'IC': (tr or {}).get('ic')})
    tr = _eval_w(cache, best_w, train, h, topn, filt)
    te = _eval_w(cache, best_w, test, h, topn, filt)
    cmp.append({'策略': '★优化后', '训练_超额%': round((tr or {}).get('excess', 0) * 100, 2),
                '留出_超额%': round((te or {}).get('excess', 0) * 100, 2), 'IC': (tr or {}).get('ic')})
    return {'ok': True, 'periods': periods, 'train': train, 'test': test, 'h': h, 'topn': topn, 'filter': filt,
            'weights': best_w, 'trajectory': traj, 'compare': cmp,
            'final': {'train': tr, 'test': te},
            'note': '训练期=%s，留出期=%s；只在训练期优化权重，留出期仅验证。' % ('、'.join(train), '、'.join(test))}
