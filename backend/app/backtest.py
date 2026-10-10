# -*- coding: utf-8 -*-
"""无未来函数（no look-ahead）回测引擎。

铁律：
- 信号（选股）只用「决策日 T0 及之前已可得」的信息：即 2026-06-30 报告期的财报快照，
  其法定披露截止为 2026-08-31，故 T0 取 2026-09-01。
- 收益只用「T0 之后」的前复权 K 线（warehouse.kline）。
- 二者时间上严格不重叠，杜绝未来函数。
"""
import math
from . import warehouse, strategy

PUBLISH_DONE = '2026-09-01'


def _z(vals, v):
    xs = [x for x in vals if isinstance(x, (int, float))]
    if not isinstance(v, (int, float)) or len(xs) < 5:
        return None
    mu = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs)) or 1e-9
    return max(-3.0, min(3.0, (v - mu) / sd))


def _spearman(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    def rank(a):
        order = sorted(range(n), key=lambda i: a[i])
        r = [0.0] * n
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    return round(num / (dx * dy), 4) if dx * dy else None


def _kl_all():
    with warehouse.cursor() as c:
        rs = c.execute('SELECT code, date, close FROM kline ORDER BY code, date').fetchall()
    out = {}
    for code, date, close in rs:
        out.setdefault(code, []).append((date, close))
    return out


def _fwd(series, t0, h):
    idx = None
    for i, (d, _c) in enumerate(series):
        if d >= t0:
            idx = i
            break
    if idx is None or idx + h >= len(series):
        return None
    c0, c1 = series[idx][1], series[idx + h][1]
    if not c0:
        return None
    return c1 / c0 - 1.0


def _median(v):
    xs = sorted(x for x in v if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def _snapshot_scored():
    d, rows = warehouse.market_snap()
    _W = strategy.weights()
    for k in ('np_yoy', 'rev_yoy', 'roe', 'gm'):
        vals = [r.get(k) for r in rows if isinstance(r.get(k), (int, float))]
        if len(vals) < 2:
            mu, sd = 0.0, 1.0
        else:
            mu = sum(vals) / len(vals)
            sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / len(vals)) or 1e-9
        for r in rows:
            v = r.get(k)
            r['z_' + k] = (max(-3.0, min(3.0, (v - mu) / sd)) if isinstance(v, (int, float)) else None)
    for r in rows:
        num = sum(_W.get(k, 0.0) * (r.get('z_' + k) or 0) for k in ('np_yoy', 'rev_yoy', 'roe', 'gm'))
        r['mfac'] = round(50 + num * 15, 2)
    return d, rows


ROUNDS = [
    {'name': 'R1 基准：全市场等权', 'sig': None, 'n': None},
    {'name': 'R2 综合分 Top20', 'sig': 'mfac', 'n': 20},
    {'name': 'R3 净利增速 Top20', 'sig': 'np_yoy', 'n': 20},
    {'name': 'R4 ROE Top20', 'sig': 'roe', 'n': 20},
    {'name': 'R5 营收增速 Top20', 'sig': 'rev_yoy', 'n': 20},
    {'name': 'R6 毛利率 Top20', 'sig': 'gm', 'n': 20},
    {'name': 'R7 综合分 Top20（剔除亏损/暴雷）', 'sig': 'mfac', 'n': 20, 'exclude': ['亏损', '暴雷']},
    {'name': 'R8 综合分 Top20（ROE>=10）', 'sig': 'mfac', 'n': 20, 'min_roe': 10},
    {'name': 'R9 综合分 Top10', 'sig': 'mfac', 'n': 10},
    {'name': 'R10 综合分 Top20（H=5）', 'sig': 'mfac', 'n': 20, 'h': 5},
]


def _one(cfg, snap, kl, t0):
    h = cfg.get('h', 10)
    uni = []
    for code, row in snap.items():
        s = kl.get(code)
        if not s:
            continue
        fr = _fwd(s, t0, h)
        if fr is None:
            continue
        uni.append({'code': code, 'row': row, 'ret': fr})
    if not uni:
        return {'name': cfg['name'], 'h': h, 'error': '无可用样本（K 线覆盖不足）'}
    bench = sum(x['ret'] for x in uni) / len(uni)
    cand = list(uni)
    if cfg.get('exclude'):
        ex = cfg['exclude']
        cand = [x for x in cand if not any(t in (x['row'].get('tag') or '') for t in ex)]
    if cfg.get('min_roe') is not None:
        cand = [x for x in cand if (x['row'].get('roe') if isinstance(x['row'].get('roe'), (int, float)) else -1e9) >= cfg['min_roe']]
    sig = cfg.get('sig')
    if sig:
        cand = [x for x in cand if isinstance(x['row'].get(sig), (int, float))]
        cand = sorted(cand, key=lambda x: -x['row'][sig])
    n = cfg.get('n')
    hold = cand[:n] if n else cand
    if not hold:
        return {'name': cfg['name'], 'h': h, 'error': '筛选后无标的'}
    rets = [x['ret'] for x in hold]
    port = sum(rets) / len(rets)
    ic = None
    if sig:
        cv = [x for x in uni if isinstance(x['row'].get(sig), (int, float))]
        if len(cv) >= 5:
            ic = _spearman([x['row'][sig] for x in cv], [x['ret'] for x in cv])
    hits = sum(1 for r in rets if r > 0)
    return {'name': cfg['name'], 'h': h, 'n_hold': len(hold), 'universe': len(uni),
            'ret': round(port, 4), 'bench': round(bench, 4), 'excess': round(port - bench, 4),
            'hit': round(100.0 * hits / len(rets), 1), 'median': round(_median(rets), 4), 'ic': ic,
            'holdings': [{'code': x['code'], 'name': x['row'].get('name'), 'ret': round(x['ret'], 4)} for x in hold[:12]]}


ENTRY = ['2026-09-01', '2026-09-08', '2026-09-15', '2026-09-22']


def walkforward(h=5):
    """多入场日稳健性：同一（披露后的）信号，在不同入场日进场，检验是否稳定。
    所有入场日均在 2026-08-31 披露截止之后 —— 依然无未来函数。"""
    d, rows = _snapshot_scored()
    snap = {r['code']: r for r in rows}
    kl = _kl_all()
    out = []
    for t0 in ENTRY:
        cfg = {'name': '综合分 Top20', 'sig': 'mfac', 'n': 20, 'h': h}
        r = _one(cfg, snap, kl, t0)
        out.append({'t0': t0, 'ret': r.get('ret'), 'bench': r.get('bench'), 'excess': r.get('excess'),
                    'hit': r.get('hit'), 'n_hold': r.get('n_hold'), 'universe': r.get('universe')})
    return {'ok': True, 'h': h, 'entry_dates': out}


def run_all(t0=PUBLISH_DONE):
    d, rows = _snapshot_scored()
    snap = {r['code']: r for r in rows}
    kl = _kl_all()
    out = [_one(cfg, snap, kl, t0) for cfg in ROUNDS]
    return {'ok': True, 't0': t0, 'snap_date': d, 'kline_codes': len(kl), 'rounds': out}
