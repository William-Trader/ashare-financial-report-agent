# -*- coding: utf-8 -*-
"""指标库 + 同比/环比。输入 normalize.canonical() 的结果。"""
from .normalize import find_period


def _get(stmt, date):
    it = find_period(stmt, date)
    return it['values'] if it else {}


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _sub(a, b):
    if a is None or b is None:
        return None
    return a - b


def _div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def _pct(a, b):
    r = _div(a, b)
    return None if r is None else r * 100.0


def _growth(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev) * 100.0


def _prev_period(dates, date):
    """同一会计年度内的上一报告期（用于累计->单季拆分）。"""
    cand = [d for d in dates if d < date and d[:4] == date[:4]]
    return max(cand) if cand else None


def _prev_year_same(dates, date):
    """上年同期（用于同比）。"""
    y = str(int(date[:4]) - 1)
    target = y + date[4:]
    if target in dates:
        return target
    cand = [d for d in dates if d[:4] == y]
    return max(cand) if cand else None


def single_quarter_map(stmt, field):
    """累计流量 -> 单季值：Q2单季 = H1累计 - Q1累计。"""
    dates = sorted([it['date'] for it in stmt], reverse=True)
    out = {}
    for d in dates:
        cum = _get(stmt, d).get(field)
        if cum is None:
            continue
        p = _prev_period(dates, d)
        if p is None:
            out[d] = cum
        else:
            pv = _get(stmt, p).get(field)
            out[d] = cum if pv is None else cum - pv
    return out


def compute(canon):
    bs = canon['资产负债表']
    is_ = canon['利润表']
    cf = canon['现金流量表']
    is_dates = sorted([it['date'] for it in is_], reverse=True)
    cf_dates = sorted([it['date'] for it in cf], reverse=True)

    sq_rev = single_quarter_map(is_, '营业总收入')
    sq_pnp = single_quarter_map(is_, '归母净利润')
    sq_dpnp = single_quarter_map(is_, '扣非归母净利润')
    sq_ocf = single_quarter_map(cf, '经营活动现金流净额')

    rows = []
    for d in is_dates:
        isv = _get(is_, d)
        bsv = _get(bs, d)
        cfv = _get(cf, d)

        total_assets = _num(bsv.get('总资产'))
        total_liab = _num(bsv.get('总负债'))
        total_equity = _num(bsv.get('所有者权益合计'))
        minority = _num(bsv.get('少数股东权益')) or 0.0
        parent_equity = None if total_equity is None else total_equity - minority

        ca = _num(bsv.get('流动资产合计'))
        cl = _num(bsv.get('流动负债合计'))
        inventory = _num(bsv.get('存货'))
        ar = _num(bsv.get('应收账款'))
        goodwill = _num(bsv.get('商誉'))
        st_loan = _num(bsv.get('短期借款')) or 0.0
        lt_loan = _num(bsv.get('长期借款')) or 0.0

        rev = _num(isv.get('营业总收入'))
        cost = _num(isv.get('营业成本'))
        np_ = _num(isv.get('净利润'))
        pnp = _num(isv.get('归母净利润'))
        dpnp = _num(isv.get('扣非归母净利润'))
        eps = _num(isv.get('基本每股收益'))

        ocf = _num(cfv.get('经营活动现金流净额'))
        icf = _num(cfv.get('投资活动现金流净额'))
        fcf_fin = _num(cfv.get('筹资活动现金流净额'))
        sales_cash = _num(cfv.get('销售商品提供劳务收到的现金'))

        yoy_rev = _growth(sq_rev.get(d), sq_rev.get(_prev_year_same(is_dates, d)))
        yoy_pnp = _growth(sq_pnp.get(d), sq_pnp.get(_prev_year_same(is_dates, d)))
        yoy_dpnp = _growth(sq_dpnp.get(d), sq_dpnp.get(_prev_year_same(is_dates, d)))
        yoy_ocf = _growth(sq_ocf.get(d), sq_ocf.get(_prev_year_same(cf_dates, d)))
        qoq_rev = _growth(sq_rev.get(d), sq_rev.get(_prev_period(is_dates, d)))
        qoq_pnp = _growth(sq_pnp.get(d), sq_pnp.get(_prev_period(is_dates, d)))

        indices = {
            '毛利率%': _pct(_sub(rev, cost), rev),
            '净利率%': _pct(np_, rev),
            '归母净利率%': _pct(pnp, rev),
            '销售费用率%': _pct(_num(isv.get('销售费用')), rev),
            '管理费用率%': _pct(_num(isv.get('管理费用')), rev),
            '研发费用率%': _pct(_num(isv.get('研发费用')) or _num(isv.get('研发费用(合并)')), rev),
            '财务费用率%': _pct(_num(isv.get('财务费用')), rev),
            'ROE(归母权益)%': _pct(pnp, parent_equity),
            'ROA%': _pct(np_, total_assets),
            '资产负债率%': _pct(total_liab, total_assets),
            '流动比率': _div(ca, cl),
            '速动比率': _div(_sub(ca, inventory), cl),
            '有息负债率%': _pct(st_loan + lt_loan, total_assets),
            '净现比': _div(ocf, np_),
            '收现比': _div(sales_cash, rev),
            '扣非占比%': _pct(dpnp, pnp),
            '商誉占归母权益%': _pct(goodwill, parent_equity),
            '应收账款(元)': ar,
            '存货(元)': inventory,
            '经营现金流(元)': ocf,
            '投资现金流(元)': icf,
            '筹资现金流(元)': fcf_fin,
            '基本每股收益': eps,
            '单季营业总收入(元)': sq_rev.get(d),
            '单季归母净利润(元)': sq_pnp.get(d),
            '单季经营现金流(元)': sq_ocf.get(d),
            '单季营收同比%': yoy_rev,
            '单季归母净利同比%': yoy_pnp,
            '单季扣非同比%': yoy_dpnp,
            '单季经营现金流同比%': yoy_ocf,
            '单季营收环比%': qoq_rev,
            '单季归母净利环比%': qoq_pnp,
        }
        it = find_period(is_, d) or {}
        rows.append({'date': d, 'type': it.get('type', ''), 'report_name': it.get('name', ''), 'indices': indices})
    return {'code': canon['code'], 'name': canon['name'], 'rows': rows}
