# -*- coding: utf-8 -*-
"""学术级盈余质量 / 舞弊 / 破产风险评分（基于三大报表）。"""
from .normalize import find_period


def _n(v):
    return v if isinstance(v, (int, float)) else None


def _g(stmt, date):
    it = find_period(stmt, date)
    return it['values'] if it else {}


def _prev_year(dates, d):
    y = str(int(d[:4]) - 1)
    t = y + d[4:]
    if t in dates:
        return t
    cand = [x for x in dates if x[:4] == y]
    return max(cand) if cand else None


def _prev(dates, d):
    cand = [x for x in dates if x < d]
    return max(cand) if cand else None


def _div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def _ratio(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return cur / prev


def _pick_annual(dates):
    ann = [d for d in dates if d[5:7] == '12']
    return ann[0] if ann else (dates[0] if dates else None)


def beneish(canon):
    """Beneish M-Score（8 变量，年度口径）。"""
    bs, is_, cf = canon['资产负债表'], canon['利润表'], canon['现金流量表']
    dates = sorted([it['date'] for it in is_], reverse=True)
    t = _pick_annual(dates)
    if not t:
        return None
    p = _prev_year(dates, t)
    if not p:
        return None
    bt, bp = _g(bs, t), _g(bs, p)
    it_, ip = _g(is_, t), _g(is_, p)
    ct, cp = _g(cf, t), _g(cf, p)

    def v(dic, k):
        return _n(dic.get(k))

    dsri = _ratio(_div(v(bt, '应收账款'), v(it_, '营业总收入')), _div(v(bp, '应收账款'), v(ip, '营业总收入')))
    gm_t = _div((v(it_, '营业总收入') or 0) - (v(it_, '营业成本') or 0), v(it_, '营业总收入'))
    gm_p = _div((v(ip, '营业总收入') or 0) - (v(ip, '营业成本') or 0), v(ip, '营业总收入'))
    gmi = _ratio(gm_p, gm_t)
    aqi_t = _div(1 - _div((v(bt, '流动资产合计') or 0) + (v(bt, '固定资产') or 0), v(bt, '总资产')),
                 1) if v(bt, '总资产') else None
    aqi_p = _div(1 - _div((v(bp, '流动资产合计') or 0) + (v(bp, '固定资产') or 0), v(bp, '总资产')),
                 1) if v(bp, '总资产') else None
    aqi = _ratio(aqi_t, aqi_p)
    sgi = _ratio(v(it_, '营业总收入'), v(ip, '营业总收入'))
    dep_t = (v(ct, '固定资产折旧等') or 0) + (v(ct, '无形资产摊销') or 0)
    dep_p = (v(cp, '固定资产折旧等') or 0) + (v(cp, '无形资产摊销') or 0)
    rate_t = _div(dep_t, dep_t + (v(bt, '固定资产') or 0))
    rate_p = _div(dep_p, dep_p + (v(bp, '固定资产') or 0))
    depi = _ratio(rate_p, rate_t)
    sgai = _ratio(_div((v(it_, '销售费用') or 0) + (v(it_, '管理费用') or 0), v(it_, '营业总收入')),
                  _div((v(ip, '销售费用') or 0) + (v(ip, '管理费用') or 0), v(ip, '营业总收入')))
    lvgi = _ratio(_div(v(bt, '总负债'), v(bt, '总资产')), _div(v(bp, '总负债'), v(bp, '总资产')))
    tata = _div((v(it_, '净利润') or 0) - (v(ct, '经营活动现金流净额') or 0), v(bt, '总资产'))

    parts = {'DSRI': dsri, 'GMI': gmi, 'AQI': aqi, 'SGI': sgi, 'DEPI': depi, 'SGAI': sgai, 'LVGI': lvgi, 'TATA': tata}
    def d(x):
        return 1.0 if x is None else x
    m = (-4.84 + 0.920 * d(dsri) + 0.528 * d(gmi) + 0.404 * d(aqi) + 0.892 * d(sgi)
         + 0.115 * d(depi) - 0.172 * d(sgai) + 4.679 * d(tata) - 0.327 * d(lvgi))
    return {'period': t, 'base': p, 'score': round(m, 3),
            'flag': m > -1.78, 'variables': {k: (None if v is None else round(v, 3)) for k, v in parts.items()}}


def piotroski(canon):
    """Piotroski F-Score（9 项，年度口径）。"""
    bs, is_, cf = canon['资产负债表'], canon['利润表'], canon['现金流量表']
    dates = sorted([it['date'] for it in is_], reverse=True)
    t = _pick_annual(dates)
    p = _prev_year(dates, t) if t else None
    if not t or not p:
        return None
    bt, bp = _g(bs, t), _g(bs, p)
    it_, ip = _g(is_, t), _g(is_, p)
    ct = _g(cf, t)

    def v(d, k):
        return _n(d.get(k))

    ta_t, ta_p = v(bt, '总资产'), v(bp, '总资产')
    roa_t = _div(v(it_, '净利润'), ta_t)
    roa_p = _div(v(ip, '净利润'), ta_p)
    cfo_t = v(ct, '经营活动现金流净额')
    signals = [
        ('ROA>0', 1 if (roa_t or 0) > 0 else 0),
        ('CFO>0', 1 if (cfo_t or 0) > 0 else 0),
        ('ΔROA>0', 1 if (roa_t is not None and roa_p is not None and roa_t > roa_p) else 0),
        ('CFO>ROA', 1 if (roa_t is not None and cfo_t is not None and _div(cfo_t, ta_t) is not None and _div(cfo_t, ta_t) > roa_t) else 0),
        ('杠杆下降', 1 if _div(v(bt, '长期借款'), ta_t) is not None and _div(v(bp, '长期借款'), ta_p) is not None and _div(v(bt, '长期借款'), ta_t) < _div(v(bp, '长期借款'), ta_p) else 0),
        ('流动比率上升', 1 if _div(v(bt, '流动资产合计'), v(bt, '流动负债合计')) is not None and _div(v(bp, '流动资产合计'), v(bp, '流动负债合计')) is not None and _div(v(bt, '流动资产合计'), v(bt, '流动负债合计')) > _div(v(bp, '流动资产合计'), v(bp, '流动负债合计')) else 0),
        ('未增发', 1 if (v(bt, '股本') or 0) <= (v(bp, '股本') or 0) else 0),
        ('毛利率上升', 1 if _div((v(it_, '营业总收入') or 0) - (v(it_, '营业成本') or 0), v(it_, '营业总收入')) is not None and _div((v(ip, '营业总收入') or 0) - (v(ip, '营业成本') or 0), v(ip, '营业总收入')) is not None and _div((v(it_, '营业总收入') or 0) - (v(it_, '营业成本') or 0), v(it_, '营业总收入')) > _div((v(ip, '营业总收入') or 0) - (v(ip, '营业成本') or 0), v(ip, '营业总收入')) else 0),
        ('资产周转率上升', 1 if _div(v(it_, '营业总收入'), ta_t) is not None and _div(v(ip, '营业总收入'), ta_p) is not None and _div(v(it_, '营业总收入'), ta_t) > _div(v(ip, '营业总收入'), ta_p) else 0),
    ]
    score = sum(s[1] for s in signals)
    return {'period': t, 'score': score, 'level': '强' if score >= 7 else ('中' if score >= 4 else '弱'),
            'signals': [{'name': s[0], 'pass': bool(s[1])} for s in signals]}


def altman_z(canon):
    """Altman Z''-Score（新兴/非上市变体，不依赖市值）。"""
    bs, is_ = canon['资产负债表'], canon['利润表']
    dates = sorted([it['date'] for it in is_], reverse=True)
    t = _pick_annual(dates) or (dates[0] if dates else None)
    if not t:
        return None
    b, i = _g(bs, t), _g(is_, t)

    def v(d, k):
        return _n(d.get(k))

    ta = v(b, '总资产')
    wc = (v(b, '流动资产合计') or 0) - (v(b, '流动负债合计') or 0)
    re_ = (v(b, '归母权益合计') or v(b, '所有者权益合计') or 0) - (v(b, '股本') or 0) - (v(b, '资本公积') or 0)
    ebit = (v(i, '利润总额') or 0) + abs(v(i, '财务费用') or 0)
    x1, x2, x3 = _div(wc, ta), _div(re_, ta), _div(ebit, ta)
    x4 = _div(v(b, '归母权益合计') or v(b, '所有者权益合计'), v(b, '总负债'))
    if None in (x1, x2, x3, x4):
        return None
    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    return {'period': t, 'score': round(z, 2),
            'zone': '安全' if z > 2.6 else ('灰色' if z >= 1.1 else '危险'),
            'parts': {'X1': round(x1, 3), 'X2': round(x2, 3), 'X3': round(x3, 3), 'X4': round(x4, 3)}}


def sloan_accruals(canon):
    """Sloan 应计比率：越高说明利润含金量越低。"""
    bs, is_, cf = canon['资产负债表'], canon['利润表'], canon['现金流量表']
    dates = sorted([it['date'] for it in is_], reverse=True)
    out = []
    for d in dates[:4]:
        ta = _n(_g(bs, d).get('总资产'))
        npf = _n(_g(is_, d).get('净利润'))
        ocf = _n(_g(cf, d).get('经营活动现金流净额'))
        r = _div((npf or 0) - (ocf or 0), ta) if ta else None
        out.append({'period': d, 'accrual_ratio': None if r is None else round(r, 4),
                    'level': None if r is None else ('高' if abs(r) > 0.10 else ('中' if abs(r) > 0.05 else '低'))})
    return out


def run(canon):
    return {'beneish': beneish(canon), 'piotroski': piotroski(canon),
            'altman': altman_z(canon), 'accruals': sloan_accruals(canon)}
