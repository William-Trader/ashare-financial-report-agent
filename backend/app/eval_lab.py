# -*- coding: utf-8 -*-
"""评估实验室：效力验证（数百轮）。

三类检验：
  A. 横截面分层回测：多报告期 × 随机抽样 数百轮 → IC / 五档分层收益 / 单调性
  B. 预测量效检验：财报标签（暴雷/亏损/爆发/正常）→ 前向收益与负收益概率
  C. 造假案例验证：红旗引擎在已知造假/暴雷公司上的命中率
"""
import random
from . import lab, backtest as bt, fraudcases

TAG_OF = lambda t: '暴雷' if '暴雷' in (t or '') else ('亏损' if '亏损' in (t or '') else ('爆发' if '爆发' in (t or '') else '正常'))


def cross_section(draws=400, seed=7):
    cache = lab._prep()
    keys = list(cache.keys())
    rnd = random.Random(seed)
    rounds = []
    for i in range(draws):
        d, h = keys[rnd.randrange(len(keys))]
        f = rnd.choice(lab.FACTORS)
        filt = rnd.choice(list(lab.FILTERS.keys()))
        n = rnd.choice(lab.TOPN)
        r = lab._eval(cache[(d, h)], f, filt, n)
        if r:
            rounds.append({'轮次': i + 1, '报告期': d, '持有期': h, '因子': f, '过滤': filt, '持仓': n,
                           '组合收益%': round(r['ret'] * 100, 2), '基准%': round(r['bench'] * 100, 2),
                           '超额%': round(r['excess'] * 100, 2), 'IC': r['ic'], '命中率%': r['hit']})
    deciles = []
    for (d, h), uni in cache.items():
        for f in lab.FACTORS:
            vals = [(x['row'].get(f), x['ret']) for x in uni if isinstance(x['row'].get(f), (int, float))]
            if len(vals) < 40:
                continue
            vals.sort(key=lambda t: t[0])
            qn = len(vals) // 5
            ds = []
            for q in range(5):
                seg = vals[q * qn:(q + 1) * qn]
                ds.append(round(sum(s[1] for s in seg) / len(seg) * 100, 2) if seg else None)
            deciles.append({'报告期': d, '持有期': h, '因子': f, 'Q1%': ds[0], 'Q2%': ds[1], 'Q3%': ds[2],
                            'Q4%': ds[3], 'Q5%': ds[4],
                            'Q5-Q1%': (round(ds[4] - ds[0], 2) if (ds[0] is not None and ds[4] is not None) else None),
                            'IC': bt._spearman([v[0] for v in vals], [v[1] for v in vals]), '样本': len(vals)})
    exs = [e['超额%'] for e in rounds]
    ics = [e['IC'] for e in rounds if e.get('IC') is not None]
    summ = {'轮次': len(rounds),
            '平均超额%': round(sum(exs) / len(exs), 2) if exs else None,
            '胜率%': round(100.0 * sum(1 for x in exs if x > 0) / len(exs), 1) if exs else None,
            '平均IC': round(sum(ics) / len(ics), 4) if ics else None,
            '覆盖报告期': sorted(set(e['报告期'] for e in rounds))}
    return {'rounds': rounds, 'deciles': deciles, 'summary': summ}


def risk_power(h=20):
    cache = lab._prep()
    rows = []
    for (d, hh), uni in cache.items():
        if hh != h:
            continue
        by = {}
        for x in uni:
            by.setdefault(TAG_OF(x['row'].get('tag')), []).append(x['ret'])
        for k in ('暴雷', '亏损', '正常', '爆发'):
            v = by.get(k) or []
            if not v:
                continue
            rows.append({'报告期': d, '标签': k, '样本': len(v),
                         '平均前向收益%': round(sum(v) / len(v) * 100, 2),
                         '负收益概率%': round(100.0 * sum(1 for x in v if x < 0) / len(v), 1)})
    rows.sort(key=lambda x: (x['报告期'], x['标签']))
    return {'h': h, 'rows': rows}


def fraud_summary():
    r = fraudcases.run_cases()
    ok, nodata = [], []
    for c in r.get('cases') or []:
        (ok if c.get('flags_n', 0) > 0 or c.get('risk_score') else nodata).append(c)
    hit = sum(1 for c in ok if (c.get('flags_n', 0) >= 3 or c.get('risk_level') == '高'))
    return {'evaluable': len(ok), 'no_data': len(nodata), 'hit': hit,
            'hit_rate%': round(100.0 * hit / len(ok), 1) if ok else None,
            'cases': r.get('cases') or []}


def all_eval(draws=400):
    return {'ok': True, 'cross_section': cross_section(draws), 'risk_power': risk_power(), 'fraud': fraud_summary()}
