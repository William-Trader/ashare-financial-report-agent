# -*- coding: utf-8 -*-
"""异常信号：非经常性损益 / 利润-现金流背离 / 口径与结构突变。"""
from .normalize import find_period


def _g(stmt, date):
    it = find_period(stmt, date)
    return it['values'] if it else {}


def _n(v):
    return v if isinstance(v, (int, float)) else None


def _prev_year(dates, d):
    cand = [x for x in dates if x < d and x[:4] == str(int(d[:4]) - 1)]
    return max(cand) if cand else None


def _rel(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev) * 100.0


def run(canon, ind):
    is_ = canon['利润表']
    bs = canon['资产负债表']
    cf = canon['现金流量表']
    dates = sorted([it['date'] for it in is_], reverse=True)
    rows = {r['date']: r['indices'] for r in ind.get('rows', [])}
    out = []

    for d in dates[:6]:
        p = _g(is_, d)
        idx = rows.get(d, {})
        pnp = _n(p.get('归母净利润'))
        dpnp = _n(p.get('扣非归母净利润'))
        netp = _n(p.get('净利润'))
        ocf = _n(idx.get('经营现金流(元)'))
        y = _prev_year(dates, d)
        py = _g(is_, y) if y else {}

        if pnp is not None and dpnp is not None and pnp != 0:
            extra = pnp - dpnp
            ratio = extra / abs(pnp) * 100.0
            if abs(ratio) >= 30:
                lvl = 'high' if abs(ratio) >= 60 else 'medium'
                out.append({'level': lvl, 'category': '非经常性损益', 'period': d,
                    'title': '非经常性损益占归母净利润 ' + str(round(ratio, 1)) + '%',
                    'detail': '归母净利润 ' + _fmt(pnp) + '，扣非后 ' + _fmt(dpnp) + '，差额 ' + _fmt(extra) + '。利润对非经常项目依赖较高，持续性存疑。',
                    'evidence': ['利润表: 归母净利润=' + _fmt(pnp), '利润表: 扣非归母净利润=' + _fmt(dpnp)]})
            if dpnp is not None and dpnp < 0 <= pnp:
                out.append({'level': 'high', 'category': '非经常性损益', 'period': d,
                    'title': '扣非为负而账面盈利（非经常性损益扭亏）',
                    'detail': '归母净利润为正而扣非归母净利润为负，主业实际亏损，靠非经常项目扭亏。',
                    'evidence': ['利润表: 归母净利润=' + _fmt(pnp), '利润表: 扣非归母净利润=' + _fmt(dpnp)]})

        if netp is not None and ocf is not None and netp > 0:
            ratio = ocf / netp
            if ratio < 0.3:
                out.append({'level': 'high', 'category': '利润与现金流背离', 'period': d,
                    'title': '净现比仅 ' + str(round(ratio, 2)) + '（利润含金量低）',
                    'detail': '经营现金流仅为净利润的 ' + str(round(ratio * 100, 1)) + '%，盈利未有效转化为现金。',
                    'evidence': ['利润表: 净利润=' + _fmt(netp), '现金流量表: 经营活动现金流净额=' + _fmt(ocf)]})
            elif ratio < 0.7:
                out.append({'level': 'medium', 'category': '利润与现金流背离', 'period': d,
                    'title': '净现比 ' + str(round(ratio, 2)) + '（低于 0.7）',
                    'detail': '经营现金流/净利润偏低，关注应收账款与存货占用。',
                    'evidence': ['利润表: 净利润=' + _fmt(netp), '现金流量表: 经营活动现金流净额=' + _fmt(ocf)]})
        if ocf is not None and ocf < 0:
            out.append({'level': 'high', 'category': '利润与现金流背离', 'period': d,
                'title': '经营活动现金流为负',
                'detail': '本期经营活动净现金流为负，主业造血能力不足。',
                'evidence': ['现金流量表: 经营活动现金流净额=' + _fmt(ocf)]})

        if py:
            g_np = _rel(pnp, _n(py.get('归母净利润')))
            g_ocf = _rel(ocf, _n(_g(cf, y).get('经营活动现金流净额')))
            if g_np is not None and g_ocf is not None and (g_np - g_ocf) >= 30:
                out.append({'level': 'medium', 'category': '利润与现金流背离', 'period': d,
                    'title': '净利润增速显著高于经营现金流增速',
                    'detail': '归母净利同比 ' + str(round(g_np, 1)) + '%，经营现金流同比 ' + str(round(g_ocf, 1)) + '%，剪刀差 ' + str(round(g_np - g_ocf, 1)) + 'pct。',
                    'evidence': ['利润表: 归母净利润同比', '现金流量表: 经营现金流净额同比']})
            mg_now = idx.get('毛利率%')
            mg_prev = rows.get(y, {}).get('毛利率%')
            if mg_now is not None and mg_prev is not None and abs(mg_now - mg_prev) >= 5:
                out.append({'level': 'medium', 'category': '会计口径/结构变化', 'period': d,
                    'title': '毛利率同比变动 ' + str(round(mg_now - mg_prev, 1)) + 'pct',
                    'detail': '毛利率 ' + str(round(mg_prev, 1)) + '% -> ' + str(round(mg_now, 1)) + '%，需核对成本口径/产品结构/会计政策变更。',
                    'evidence': ['利润表: 营业成本/营业总收入']})
            ar_now = idx.get('应收账款(元)')
            rev_g = idx.get('单季营收同比%')
            ar_prev = rows.get(y, {}).get('应收账款(元)')
            ar_g = _rel(ar_now, ar_prev)
            if ar_g is not None and rev_g is not None and (ar_g - rev_g) >= 20:
                out.append({'level': 'medium', 'category': '利润与现金流背离', 'period': d,
                    'title': '应收账款增速远超营收增速',
                    'detail': '应收同比 ' + str(round(ar_g, 1)) + '%，营收同比 ' + str(round(rev_g, 1)) + '%，回款压力上升。',
                    'evidence': ['资产负债表: 应收账款', '利润表: 营业总收入']})

        gs = _n(_g(bs, d).get('商誉'))
        te = _n(_g(bs, d).get('所有者权益合计'))
        if gs is not None and te not in (None, 0) and gs / te >= 0.3:
            out.append({'level': 'medium', 'category': '资产质量', 'period': d,
                'title': '商誉占净资产 ' + str(round(gs / te * 100, 1)) + '%',
                'detail': '商誉减值是潜在利润冲击点。',
                'evidence': ['资产负债表: 商誉 / 所有者权益合计']})
    return out


def _fmt(v):
    if v is None:
        return 'N/A'
    a = abs(v)
    if a >= 1e8:
        return str(round(v / 1e8, 2)) + '亿'
    if a >= 1e4:
        return str(round(v / 1e4, 2)) + '万'
    return str(round(v, 2))
