# -*- coding: utf-8 -*-
"""表内 / 表间勾稽校验。"""
from .normalize import find_period


def _g(stmt, date):
    it = find_period(stmt, date)
    return it['values'] if it else {}


def _n(v):
    return v if isinstance(v, (int, float)) else None


def _cmp(name, lhs, rhs, tol_rel=0.005, unit='元', formula='', period=''):
    if lhs is None or rhs is None:
        return {'name': name, 'period': period, 'status': 'skip', 'formula': formula,
                'detail': '数据缺失，无法校验'}
    diff = lhs - rhs
    base = max(abs(lhs), abs(rhs), 1.0)
    rel = abs(diff) / base
    if rel <= tol_rel:
        status = 'pass'
    elif rel <= 0.05:
        status = 'warn'
    else:
        status = 'fail'
    return {
        'name': name, 'period': period, 'status': status, 'formula': formula,
        'left': lhs, 'right': rhs, 'diff': diff, 'diff_pct': rel * 100.0,
        'detail': '左=右' if status == 'pass' else ('差额 ' + str(round(diff, 2)) + unit),
    }


def run(canon):
    bs = canon['资产负债表']
    is_ = canon['利润表']
    cf = canon['现金流量表']
    out = []
    for it in bs:
        d = it['date']
        b = _g(bs, d)
        p = _g(is_, d)
        c = _g(cf, d)
        ta = _n(b.get('总资产'))
        tl = _n(b.get('总负债'))
        te = _n(b.get('所有者权益合计'))
        if ta is not None and tl is not None and te is not None:
            out.append(_cmp('资产负债表平衡：资产 = 负债 + 所有者权益', ta, tl + te,
                            formula='总资产 = 总负债 + 所有者权益合计', period=d))
        ca = _n(b.get('流动资产合计'))
        cl = _n(b.get('流动负债合计'))
        na = _n(b.get('非流动资产合计'))
        nl = _n(b.get('非流动负债合计'))
        if None not in (ca, na, ta):
            out.append(_cmp('资产分类合计：流动 + 非流动 = 总资产', ca + na, ta,
                            formula='流动资产 + 非流动资产 = 总资产', period=d))
        if None not in (cl, nl, tl):
            out.append(_cmp('负债分类合计：流动 + 非流动 = 总负债', cl + nl, tl,
                            formula='流动负债 + 非流动负债 = 总负债', period=d))
        pnp = _n(p.get('归母净利润'))
        mi = _n(p.get('少数股东损益')) or 0.0
        netp = _n(p.get('净利润'))
        if None not in (pnp, netp):
            out.append(_cmp('净利润构成：归母 + 少数股东损益 = 净利润', pnp + mi, netp,
                            formula='归母净利润 + 少数股东损益 = 净利润', period=d))
        tp = _n(p.get('利润总额'))
        tax = _n(p.get('所得税费用'))
        if None not in (tp, tax, netp):
            out.append(_cmp('利润总额 - 所得税 = 净利润', tp - tax, netp,
                            formula='利润总额 - 所得税费用 = 净利润', period=d, tol_rel=0.01))
        ocf = _n(c.get('经营活动现金流净额'))
        icf = _n(c.get('投资活动现金流净额'))
        fcf = _n(c.get('筹资活动现金流净额'))
        bgn = _n(c.get('期初现金及现金等价物'))
        end = _n(c.get('期末现金及现金等价物'))
        if None not in (ocf, icf, fcf, bgn, end):
            out.append(_cmp('现金勾稽：期初 + 经营 + 投资 + 筹资 = 期末', bgn + ocf + icf + fcf, end,
                            formula='期初现金 + 经营净额 + 投资净额 + 筹资净额 = 期末现金', period=d, tol_rel=0.01))
        cnp = _n(c.get('净利润(现金流补充)'))
        if None not in (cnp, netp):
            out.append(_cmp('表间一致：现金流量表(补充)净利润 = 利润表净利润', cnp, netp,
                            formula='现金流量表补充资料净利润 = 利润表净利润', period=d, tol_rel=0.01))
    return out
