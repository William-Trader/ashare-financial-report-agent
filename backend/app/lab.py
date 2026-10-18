# -*- coding: utf-8 -*-
"""回测实验室：多报告期「随机事件」财报因子回测（无未来函数）+ 迭代。

每个报告期 P 取法定披露截止后的决策日 T0(P)，收益用 T0 之后的前复权 K 线；
信号与收益时间不重叠，杜绝未来函数。随机采样（期 × 因子 × 过滤 × 持有期 × 持仓数）
跑 N 轮，逐轮记录最优策略轨迹。
"""
import random
from . import warehouse, backtest as bt, strategy

PERIODS = [
    ('20240930', '2024-11-01'), ('20241231', '2025-05-06'), ('20250331', '2025-05-06'),
    ('20250630', '2025-09-01'), ('20250930', '2025-11-03'), ('20251231', '2026-05-06'),
    ('20260630', '2026-09-01'),
]
HORIZONS = [5, 10, 20, 40]
FILTERS = {
    '无': lambda r: True,
    '非亏损': lambda r: '亏损' not in (r.get('tag') or ''),
    '非暴雷': lambda r: '暴雷' not in (r.get('tag') or ''),
    'ROE>=10': lambda r: isinstance(r.get('roe'), (int, float)) and r['roe'] >= 10,
}
FACTORS = ['np_yoy', 'rev_yoy', 'roe', 'gm', 'mfac']
TOPN = [10, 20, 30]


def _snap(date):
    with warehouse.cursor() as c:
        rs = c.execute('SELECT code,name,board,np_yoy,rev_yoy,roe,gm,np,rev,tag FROM market_snap WHERE snap_date=?', (date,)).fetchall()
    rows = [{'code': r[0], 'name': r[1], 'board': r[2], 'np_yoy': r[3], 'rev_yoy': r[4],
             'roe': r[5], 'gm': r[6], 'np': r[7], 'rev': r[8], 'tag': r[9]} for r in rs]
    _W = strategy.weights()
    for k in ('np_yoy', 'rev_yoy', 'roe', 'gm'):
        vals = [r.get(k) for r in rows if isinstance(r.get(k), (int, float))]
        if len(vals) < 2:
            mu, sd = 0.0, 1.0
        else:
            mu = sum(vals) / len(vals)
            sd = (sum((x - mu) ** 2 for x in vals) / len(vals)) ** 0.5 or 1e-9
        for r in rows:
            v = r.get(k)
            r['z_' + k] = (max(-3.0, min(3.0, (v - mu) / sd)) if isinstance(v, (int, float)) else None)
    for r in rows:
        num = sum(_W.get(k, 0.0) * (r.get('z_' + k) or 0) for k in ('np_yoy', 'rev_yoy', 'roe', 'gm'))
        r['mfac'] = round(50 + num * 15, 2)
    return {r['code']: r for r in rows}


_PREP = None


def _prep():
    global _PREP
    if _PREP is None:
        _PREP = _prep_raw()
    return _PREP


def _prep_raw():
    kl = bt._kl_all()
    cache = {}
    for d, t0 in PERIODS:
        snap = _snap(d)
        for h in HORIZONS:
            uni = []
            for code, row in snap.items():
                s = kl.get(code)
                if not s:
                    continue
                fr = bt._fwd(s, t0, h)
                if fr is None:
                    continue
                uni.append({'code': code, 'row': row, 'ret': fr})
            if len(uni) >= 30:
                cache[(d, h)] = uni
    return cache


def _eval(uni, factor, filt, topn):
    cand = [x for x in uni if FILTERS[filt](x['row'])]
    cand = [x for x in cand if isinstance(x['row'].get(factor), (int, float))]
    if len(cand) < 20:
        return None
    bench = sum(x['ret'] for x in uni) / len(uni)
    cand.sort(key=lambda x: -x['row'][factor])
    hold = cand[:topn]
    port = sum(x['ret'] for x in hold) / len(hold)
    ic = bt._spearman([x['row'][factor] for x in cand], [x['ret'] for x in cand])
    return {'n': len(uni), 'ret': round(port, 4), 'bench': round(bench, 4),
            'excess': round(port - bench, 4), 'ic': ic,
            'hit': round(100.0 * sum(1 for x in hold if x['ret'] > 0) / len(hold), 1)}


def run(rounds=100, seed=20261007):
    cache = _prep()
    keys = list(cache.keys())
    if not keys:
        return {'ok': False, 'reason': '无可用样本（K 线覆盖不足，需先同步历史 K 线）'}
    rnd = random.Random(seed)
    entries = []
    for i in range(1, rounds + 1):
        d, h = keys[rnd.randrange(len(keys))]
        factor = rnd.choice(FACTORS)
        filt = rnd.choice(list(FILTERS.keys()))
        topn = rnd.choice(TOPN)
        r = _eval(cache[(d, h)], factor, filt, topn)
        if not r:
            continue
        entries.append({'i': i, 'period': d, 'h': h, 'factor': factor, 'filter': filt, 'topn': topn, **r})
    if not entries:
        return {'ok': False, 'reason': '评估样本不足'}
    traj, bs = [], -9.0
    for e in entries:
        bs = max(bs, e['excess'])
        traj.append(round(bs, 4))
    avg_ex = sum(e['excess'] for e in entries) / len(entries)
    win = sum(1 for e in entries if e['excess'] > 0)
    ics = [e['ic'] for e in entries if e['ic'] is not None]
    avg_ic = sum(ics) / len(ics) if ics else None
    by = {}
    for e in entries:
        by.setdefault((e['period'], e['factor'], e['filter'], e['topn']), []).append(e['excess'])
    ranked = sorted(by.items(), key=lambda kv: -(sum(kv[1]) / len(kv[1])))
    best = [{'period': k[0], 'factor': k[1], 'filter': k[2], 'topn': k[3],
             'avg_excess': round(sum(v) / len(v), 4), 'n': len(v)} for k, v in ranked[:12]]
    # 按报告期汇总
    per = {}
    for e in entries:
        per.setdefault(e['period'], []).append(e['excess'])
    byperiod = [{'period': d, 'avg_excess': round(sum(v) / len(v), 4), 'n': len(v)} for d, v in sorted(per.items())]
    # 按因子汇总
    byfac = {}
    for e in entries:
        byfac.setdefault(e['factor'], []).append(e['excess'])
    byfactor = sorted([{'factor': k, 'avg_excess': round(sum(v) / len(v), 4), 'n': len(v)} for k, v in byfac.items()],
                      key=lambda x: -x['avg_excess'])
    return {'ok': True, 'rounds': len(entries), 'seed': seed,
            'periods': sorted(set(d for d, _ in keys)), 'samples': {str(k): len(v) for k, v in cache.items()},
            'avg_excess': round(avg_ex, 4), 'win_rate': round(100.0 * win / len(entries), 1),
            'avg_ic': round(avg_ic, 4) if avg_ic is not None else None,
            'best': best, 'by_period': byperiod, 'by_factor': byfactor,
            'trajectory': traj, 'entries': entries}
