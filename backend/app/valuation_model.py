# -*- coding: utf-8 -*-
"""自动化估值建模（竞赛选题4）：DCF(FCFF) + 相对估值 + 敏感性矩阵。
所有假设显式列出、可覆盖；输出区间而非单点，并附免责。"""
import math
from .normalize import find_period
from . import realtime as rt, valuation


def _n(v):
    return v if isinstance(v, (int, float)) else None


def _g(stmt, d):
    it = find_period(stmt, d)
    return it['values'] if it else {}


def _annual(cf_dates):
    a = [d for d in cf_dates if d[5:7] == '12']
    return a[0] if a else (cf_dates[0] if cf_dates else None)


def run(code, wacc=0.09, g1=0.08, years=5, g_term=0.03, growth_fade=True, clamp=0.35):
    """默认假设：WACC 9%、前 5 年增速 8%、永续 3%。区间由敏感性给出。"""
    r = __import__('app.scanner', fromlist=['x']).analyze(code, 6 * 3600, advanced=False, periods=12)
    canon = r['canonical']
    cf, bs = canon['现金流量表'], canon['资产负债表']
    cfd = sorted([x['date'] for x in cf], reverse=True)
    bsd = sorted([x['date'] for x in bs], reverse=True)
    d = _annual(cfd)
    if not d:
        return {'ok': False, 'reason': '缺少年度现金流数据（DCF 需年末口径）'}
    c, b = _g(cf, d), _g(bs, d)
    ocf = _n(c.get('经营活动现金流净额'))
    icf = _n(c.get('投资活动现金流净额'))
    # 资本开支优先用「Δ固定资产 + 折旧摊销」估计（比投资活动净额可靠：后者含理财/存款等非资本项）
    fa, fa0 = _n(b.get('固定资产')), None
    bsd_ = sorted([x['date'] for x in bs], reverse=True)
    y0 = [x for x in bsd_ if x < d and x[5:7] == '12']
    if y0:
        fa0 = _n(_g(bs, y0[0]).get('固定资产'))
    dep = sum([(_n(c.get(k)) or 0) for k in ('固定资产折旧等', '无形资产摊销', '长期待摊费用摊销', '使用权资产摊销')])
    capex = None
    if fa is not None and fa0 is not None:
        capex = max(0.0, (fa - fa0) + dep)
    if capex is None or capex == 0:
        capex = abs(icf) if (icf is not None and icf < 0) else 0.0
        capex_src = '|投资活动净额|（回退）'
    else:
        capex_src = 'Δ固定资产+折旧摊销'
    fcf0 = (ocf or 0) - capex
    q = rt.quote(code)
    price = q.get('price') if q.get('ok') else None
    mcap = q.get('marketCap') if q.get('ok') else None

    def _rel():
        try:
            v = valuation.run(code)
            return {'pe': v.get('pe'), 'pe_percentile': v.get('pe_percentile'), 'pb': v.get('pb'),
                    'pb_percentile': v.get('pb_percentile'), 'price_percentile': v.get('price_percentile'),
                    'pe_band': [v.get('pe_min'), v.get('pe_max')]}
        except Exception:
            return {}

    _ind = ''
    try:
        from . import marketdata as _md
        _ind = ((_md.profile(code) or {}).get('industry') or '')
    except Exception:
        pass
    _fin = any(k in _ind for k in ('银行', '保险', '证券', '信托', '多元金融'))
    if fcf0 <= 0 or _fin:
        rel0 = _rel()
        why = (('金融行业（' + _ind + '）不适用 FCFF 自由现金流折现') if _fin
               else ('自由现金流为负或缺失（' + str(d) + '）'))
        pct = rel0.get('pe_percentile')
        return {'ok': True, 'method': 'relative', 'code': canon.get('code'), 'name': canon.get('name'),
                'basis_period': d, 'relative': rel0, 'dcf': None, 'sensitivity': None,
                'reason': why + '，DCF 不适用，已改用相对估值（PE/PB 历史分位）。',
                'verdict': {'price': price, 'pe_percentile': rel0.get('pe_percentile'),
                            'pb_percentile': rel0.get('pb_percentile'),
                            'read': ('按 PE/PB 历史分位看处于低位' if isinstance(pct, (int, float)) and pct < 35
                                     else ('处于高位' if isinstance(pct, (int, float)) and pct > 70 else '处于中位'))},
                'note': '金融股与自由现金流为负的标的改用相对估值；本模型为教学/研究用途，不构成投资建议。'}
    st = (_n(b.get('短期借款')) or 0) + (_n(b.get('长期借款')) or 0)
    cash = _n(b.get('货币资金')) or 0
    net_debt = st - cash
    shares = (mcap / price) if (price and mcap) else None
    if not shares:
        return {'ok': False, 'reason': '无法取得股本（行情缺失）'}

    def dcf(g1_, wacc_):
        pv = 0.0
        f = fcf0
        for t in range(1, years + 1):
            g = g1_ * ((1 - t / (years + 1.0)) if growth_fade else 1.0)   # 线性衰减到 0
            g = max(-clamp, min(clamp, g))
            f = f * (1 + g)
            pv += f / ((1 + wacc_) ** t)
        gt = max(0.0, min(g_term, wacc_ - 0.005))
        tv = f * (1 + gt) / (wacc_ - gt) if wacc_ > gt else 0.0
        pv += tv / ((1 + wacc_) ** years)
        equity = pv - net_debt
        return {'enterprise_value': pv, 'equity_value': equity,
                'per_share': equity / shares if shares else None}

    base = dcf(g1, wacc)
    # 敏感性矩阵：增速 x WACC
    gs = [g1 - 0.04, g1 - 0.02, g1, g1 + 0.02, g1 + 0.04]
    ws = [wacc - 0.02, wacc - 0.01, wacc, wacc + 0.01, wacc + 0.02]
    matrix = []
    for g in gs:
        row = []
        for w in ws:
            row.append(round((dcf(g, w).get('per_share') or 0), 2))
        matrix.append({'growth': round(g * 100, 1), 'values': row})
    vals = [row['values'][i] for row in matrix for i in range(len(ws)) if row['values'][i] > 0]
    low = round(min(vals), 2) if vals else None
    high = round(max(vals), 2) if vals else None
    rel = _rel()
    base_ps = base.get('per_share')
    sanity = None
    if price and base_ps:
        dev = (base_ps / price - 1) * 100
        if abs(dev) > 60:
            sanity = ('DCF 基准较市价偏离 %.0f%%，请优先复核资本开支代理与增速假设（矩阵已给出区间）' % dev)
    return {'ok': True, 'sanity': sanity, 'code': canon.get('code'), 'name': canon.get('name'), 'basis_period': d,
            'assumptions': {'wacc': wacc, 'stage1_growth': g1, 'years': years, 'terminal_growth': g_term,
                            'growth_fade': growth_fade, 'capex_proxy': capex_src},
            'inputs': {'fcf0': fcf0, 'ocf': ocf, 'capex_proxy': capex, 'net_debt': net_debt,
                       'shares_outstanding': shares, 'price': price, 'market_cap': mcap},
            'dcf': {'base': base, 'low': low, 'high': high},
            'sensitivity': {'growth_axis': [round(g * 100, 1) for g in gs],
                            'wacc_axis': [round(w * 100, 1) for w in ws], 'matrix': matrix},
            'relative': rel,
            'verdict': ({'price': price,
                         'vs_base': (None if not (price and base_ps) else round((price / base_ps - 1) * 100, 1)),
                         'read': ('低于 DCF 基准' if (price and base_ps and price < base_ps) else '高于 DCF 基准') if (price and base_ps) else None}),
            'note': 'DCF 对假设极敏感，矩阵即为此提供；capex 用投资活动净额近似（无购建固定资产明细）。'
                    '本模型为教学/研究用途，不构成投资建议。'}


def from_text(code, text):
    """按草稿中的财务数字核对是否存在与系统事实明显冲突。"""
    import re
    r = __import__('app.scanner', fromlist=['x']).analyze(code, 6 * 3600, advanced=False, periods=8)
    rep = r['report']
    inc = r['indicators']['rows'][0]['indices'] if r['indicators']['rows'] else {}
    pool = []
    for k, v in inc.items():
        if isinstance(v, (int, float)):
            pool.append((k, v))
    found = re.findall(r'(\d+(?:\.\d+)?)\s*(%|亿|万元|万|元)', text or '')
    return {'pool': pool[:40], 'found': found[:40], 'period': rep.get('period')}
