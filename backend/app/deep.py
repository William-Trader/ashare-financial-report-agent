# -*- coding: utf-8 -*-
"""财报深析：杜邦分解 / 周转与现金周期 / 现金流形态 / 盈利质量 / 税负 / 资产质量 / 成长一致性 / 趋势 / 评分卡。"""
import math
from .normalize import find_period

DAYS = {'03': 90, '06': 181, '09': 273, '12': 365}


def _g(stmt, date):
    it = find_period(stmt, date)
    return it['values'] if it else {}


def _n(v):
    return v if isinstance(v, (int, float)) else None


def _div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def _pct(a, b):
    r = _div(a, b)
    return None if r is None else r * 100.0


def _prev_year(dates, d):
    y = str(int(d[:4]) - 1)
    t = y + d[4:]
    if t in dates:
        return t
    c = [x for x in dates if x[:4] == y]
    return max(c) if c else None


def _prev_year_end(dates, d):
    c = [x for x in dates if x < d and x[5:7] == '12']
    return max(c) if c else None


def _days(d):
    return DAYS.get(d[5:7], 365)


def dupont(canon, date):
    bs, is_ = canon['资产负债表'], canon['利润表']
    bsd = sorted([x['date'] for x in bs], reverse=True)
    b, i = _g(bs, date), _g(is_, date)
    y0 = _prev_year_end(bsd, date)
    b0 = _g(bs, y0) if y0 else {}
    ta, ta0 = _n(b.get('总资产')), _n(b0.get('总资产'))
    eq, eq0 = _n(b.get('归母权益合计')) or _n(b.get('所有者权益合计')), _n(b0.get('归母权益合计')) or _n(b0.get('所有者权益合计'))
    avg_ta = ((ta or 0) + (ta0 or 0)) / 2 if (ta and ta0) else ta
    avg_eq = ((eq or 0) + (eq0 or 0)) / 2 if (eq and eq0) else eq
    rev, pnp = _n(i.get('营业总收入')), _n(i.get('归母净利润'))
    nm = _div(pnp, rev)
    turnover = _div(rev, avg_ta)
    em = _div(avg_ta, avg_eq)
    roe = nm * turnover * em if (nm is not None and turnover is not None and em is not None) else None
    # 同比归因
    attr = None
    if y0:
        i0 = _g(is_, _prev_year(sorted([x['date'] for x in is_], reverse=True), date) or '')
        if i0:
            pnp0 = _n(i0.get('归母净利润')); rev0 = _n(i0.get('营业总收入'))
            ta0b = _n(_g(bs, _prev_year(bsd, date) or '').get('总资产')) or ta
            eq0b = _n(_g(bs, _prev_year(bsd, date) or '').get('归母权益合计')) or eq
            nm0 = _div(pnp0, rev0); to0 = _div(rev0, ta0b); em0 = _div(ta0b, eq0b)
            if None not in (nm, turnover, em, nm0, to0, em0):
                d_nm = (nm - nm0) * to0 * em0
                d_to = nm0 * (turnover - to0) * em0
                d_em = nm0 * to0 * (em - em0)
                attr = {'净利率贡献': round(d_nm * 100, 2), '周转率贡献': round(d_to * 100, 2),
                        '权益乘数贡献': round(d_em * 100, 2),
                        'roe_now': round(roe * 100, 2) if roe else None, 'roe_prev': round(nm0 * to0 * em0 * 100, 2)}
    return {'net_margin': None if nm is None else round(nm * 100, 2),
            'asset_turnover': None if turnover is None else round(turnover, 3),
            'equity_multiplier': None if em is None else round(em, 3),
            'roe': None if roe is None else round(roe * 100, 2), 'attribution': attr,
            'note': 'ROE = 归母净利率 × 总资产周转率 × 权益乘数（用平均余额）'}


def working_capital(canon, date):
    bs, is_ = canon['资产负债表'], canon['利润表']
    bsd = sorted([x['date'] for x in bs], reverse=True)
    b, i = _g(bs, date), _g(is_, date)
    y0 = _prev_year_end(bsd, date)
    b0 = _g(bs, y0) if y0 else {}
    dd = _days(date)
    rev, cost = _n(i.get('营业总收入')), _n(i.get('营业成本'))
    ar = _n(b.get('应收账款')); ar0 = _n(b0.get('应收账款'))
    inv = _n(b.get('存货')); inv0 = _n(b0.get('存货'))
    ap = _n(b.get('应付账款')); ap0 = _n(b0.get('应付账款'))
    avg = lambda a, c: ((a or 0) + (c or 0)) / 2 if (a and c) else (a or c)
    dso = _div(avg(ar, ar0), rev)
    dio = _div(avg(inv, inv0), cost)
    dpo = _div(avg(ap, ap0), cost)
    return {'days': dd,
            'DSO_应收周转天数': None if dso is None else round(dso * dd, 1),
            'DIO_存货周转天数': None if dio is None else round(dio * dd, 1),
            'DPO_应付周转天数': None if dpo is None else round(dpo * dd, 1),
            'CCC_现金转换周期': None if None in (dso, dio, dpo) else round((dso + dio - dpo) * dd, 1),
            'note': '按当期天数年化；CCC = DSO + DIO − DPO，越小越好（占用资金越少）'}


def cashflow_profile(canon, date):
    cf = canon['现金流量表']
    c = _g(cf, date)
    o, iv, f = _n(c.get('经营活动现金流净额')), _n(c.get('投资活动现金流净额')), _n(c.get('筹资活动现金流净额'))
    sign = lambda x: '+' if (x or 0) >= 0 else '−'
    pat = sign(o) + sign(iv) + sign(f)
    LABELS = {'+++': '全面扩张（经营好+投资+融资）', '++−': '经营与投资双正、偿还融资（成熟现金牛）',
              '+−+': '经营正、投资扩产、外部融资（成长期）', '+−−': '经营正、扩产+还款（健康收缩）',
              '−++': '经营失血、靠融资与变卖维持（警惕）', '−+−': '经营失血、变卖资产还债（风险）',
              '−−+': '经营与投资双失血、靠融资（高风险）', '−−−': '全面失血（危险）'}
    capex = None
    if iv is not None:
        capex = abs(iv) if iv < 0 else 0
    fcf = None if (o is None or capex is None) else o - capex
    rev = _n(_g(canon['利润表'], date).get('营业总收入'))
    return {'operating': o, 'investing': iv, 'financing': f, 'pattern': pat,
            'label': LABELS.get(pat, ''), 'capex_approx': capex, 'fcf': fcf,
            'fcf_margin': None if (fcf is None or not rev) else round(fcf / rev * 100, 2),
            'note': '投资净额为负视为资本开支近似；FCF = 经营现金流 − 资本开支'}


def earnings_quality(canon, date):
    bs, is_, cf = canon['资产负债表'], canon['利润表'], canon['现金流量表']
    b, i, c = _g(bs, date), _g(is_, date), _g(cf, date)
    npf, pnp, dpnp = _n(i.get('净利润')), _n(i.get('归母净利润')), _n(i.get('扣非归母净利润'))
    ocf = _n(c.get('经营活动现金流净额'))
    rev = _n(i.get('营业总收入'))
    ta = _n(b.get('总资产'))
    acc = _div((npf or 0) - (ocf or 0), ta) if ta else None
    return {'cash_content_净现比': None if None in (ocf, npf) or not npf else round(ocf / npf, 2),
            'nonrecurring_share': None if None in (pnp, dpnp) or not pnp else round((pnp - dpnp) / abs(pnp) * 100, 2),
            'deducted_margin': None if None in (dpnp, rev) or not rev else round(dpnp / rev * 100, 2),
            'accrual_ratio': None if acc is None else round(acc, 4),
            'accrual_level': None if acc is None else ('高' if abs(acc) > 0.10 else ('中' if abs(acc) > 0.05 else '低')),
            'note': '净现比<1 说明利润未完全变现；应计比率越高盈余质量越低'}


def tax(canon, date):
    i = _g(canon['利润表'], date)
    tp, it_ = _n(i.get('利润总额')), _n(i.get('所得税费用'))
    rate = _pct(it_, tp)
    return {'pre_tax': tp, 'tax_expense': it_, 'effective_rate': None if rate is None else round(rate, 2),
            'vs_25': None if rate is None else round(rate - 25, 2),
            'note': '实际税率 = 所得税费用 / 利润总额；显著低于 25% 通常来自税收优惠，需核对可持续性'}


def asset_quality(canon, date):
    b = _g(canon['资产负债表'], date)
    ta = _n(b.get('总资产'))
    g, ia, ca, ar = _n(b.get('商誉')), _n(b.get('无形资产')), _n(b.get('合同负债')), _n(b.get('应收账款'))
    inv = _n(b.get('存货'))
    m = _n(b.get('货币资金'))
    return {'goodwill_pct': None if None in (g, ta) or not ta else round(g / ta * 100, 2),
            'intangible_pct': None if None in (ia, ta) or not ta else round(ia / ta * 100, 2),
            'receivable_pct': None if None in (ar, ta) or not ta else round(ar / ta * 100, 2),
            'inventory_pct': None if None in (inv, ta) or not ta else round(inv / ta * 100, 2),
            'cash_pct': None if None in (m, ta) or not ta else round(m / ta * 100, 2),
            'note': '商誉/无形占比高需关注减值风险；应收+存货占比高需关注占用与跌价'}


def growth_triangle(canon):
    is_, cf = canon['利润表'], canon['现金流量表']
    isd = sorted([x['date'] for x in is_], reverse=True)
    cfd = sorted([x['date'] for x in cf], reverse=True)
    d = isd[0] if isd else None
    if not d:
        return {}
    p = _prev_year(isd, d)
    pc = _prev_year(cfd, d)
    def g(stmt, cur, prev, f):
        a, b = _n(_g(stmt, cur).get(f)), _n(_g(stmt, prev).get(f)) if prev else None
        if a is None or b in (None, 0):
            return None
        return round((a - b) / abs(b) * 100, 2)
    tr = {'营收同比': g(is_, d, p, '营业总收入'), '归母净利同比': g(is_, d, p, '归母净利润'),
          '经营现金流同比': g(cf, d, pc, '经营活动现金流净额')}
    vals = [v for v in tr.values() if v is not None]
    cons = None
    if len(vals) == 3:
        pos = sum(1 for v in vals if v > 0)
        cons = '一致向好' if pos == 3 else ('全面承压' if pos == 0 else '背离')
    return {'period': d, **tr, 'consistency': cons,
            'note': '三项同向=一致；利润涨而现金流跌=需警惕（背离）'}


def trend(canon, periods=8):
    is_ = canon['利润表']
    rows = sorted([x['date'] for x in is_], reverse=True)[:periods]
    rows = list(reversed(rows))
    fields = ['营业总收入', '营业成本', '归母净利润', '扣非归母净利润']
    out = {'periods': rows, 'series': {}}
    for f in fields:
        vals = [_n(_g(is_, d).get(f)) for d in rows]
        out['series'][f] = vals
        cs = [v for v in vals if v is not None]
        if len(cs) >= 3 and cs[0] and cs[0] > 0:
            n = len(cs) - 1
            try:
                out.setdefault('cagr', {})[f] = round(((cs[-1] / cs[0]) ** (1.0 / n) - 1) * 100, 2)
            except Exception:
                pass
    return out


def scorecard(dup, wc, cfp, eq_, tax_, aq, gt):
    def band(v, good, bad, higher=True):
        if v is None:
            return None
        if higher:
            return 1.0 if v >= good else (0.0 if v <= bad else (v - bad) / (good - bad))
        return 1.0 if v <= good else (0.0 if v >= bad else (bad - v) / (bad - good))
    items = [
        ('ROE', dup.get('roe'), band(dup.get('roe'), 20, 5), 0.20),
        ('净利率', dup.get('net_margin'), band(dup.get('net_margin'), 20, 3), 0.10),
        ('资产周转率', dup.get('asset_turnover'), band(dup.get('asset_turnover'), 1.2, 0.3), 0.10),
        ('现金转换周期', wc.get('CCC_现金转换周期'), band(wc.get('CCC_现金转换周期'), 30, 180, higher=False), 0.10),
        ('净现比', eq_.get('cash_content_净现比'), band(eq_.get('cash_content_净现比'), 1.1, 0.4), 0.20),
        ('扣非占比', eq_.get('nonrecurring_share'), band(100 - (eq_.get('nonrecurring_share') or 0), 95, 60), 0.10),
        ('成长一致性', gt.get('consistency'), 1.0 if gt.get('consistency') == '一致向好' else (0.0 if gt.get('consistency') == '全面承压' else 0.5), 0.10),
        ('商誉占比', aq.get('goodwill_pct'), band(aq.get('goodwill_pct'), 5, 30, higher=False), 0.10),
    ]
    tot = 0.0
    wsum = 0.0
    det = []
    for name, val, sc, w in items:
        det.append({'metric': name, 'value': val, 'score': None if sc is None else round(sc, 2), 'weight': w})
        if sc is not None:
            tot += sc * w
            wsum += w
    score = round(tot / wsum * 100, 1) if wsum else None
    return {'score': score, 'grade': None if score is None else ('优' if score >= 80 else ('良' if score >= 65 else ('中' if score >= 45 else '弱'))),
            'detail': det}


def redflags(canon, ind=None):
    """财务红旗规则库：可计算、可复现、带证据。"""
    bs, is_, cf = canon['资产负债表'], canon['利润表'], canon['现金流量表']
    bsd = sorted([x['date'] for x in bs], reverse=True)
    isd = sorted([x['date'] for x in is_], reverse=True)
    d = isd[0] if isd else None
    if not d:
        return []
    b, i, c = _g(bs, d), _g(is_, d), _g(cf, d)
    py = _prev_year(isd, d)
    pby = _prev_year(bsd, d)
    b0 = _g(bs, pby) if pby else {}
    i0 = _g(is_, py) if py else {}
    flags = []

    def add(level, name, detail, ev):
        flags.append({'level': level, 'name': name, 'detail': detail, 'evidence': ev})

    ta = _n(b.get('总资产'))
    cash = _n(b.get('货币资金'))
    st, lt = _n(b.get('短期借款')) or 0, _n(b.get('长期借款')) or 0
    intb = st + lt
    # R1 存贷双高（经典舞弊特征：账上有钱却大量借债）
    if ta and cash and (cash / ta) > 0.20 and (intb / ta) > 0.20:
        add('high', '存贷双高', '货币资金占总资产 %.1f%% 且有息负债占 %.1f%%，资金充裕却高额举债，需核对资金真实性与受限情况' % (cash / ta * 100, intb / ta * 100),
            ['资产负债表: 货币资金@%s' % d, '资产负债表: 短期+长期借款@%s' % d])
    # R2 利息收入与货币资金背离
    interest_inc = _n(i.get('利息收入'))
    if interest_inc is not None and cash:
        yld = interest_inc / cash * (365.0 / _days(d)) * 100
        if yld < 0.8:
            add('high', '利息收入与货币资金背离', '推算年化收益率仅 %.2f%%，远低于正常存款利率，货币资金真实性存疑' % yld,
                ['利润表: 利息收入@%s' % d, '资产负债表: 货币资金@%s' % d])
    # R3 应收账款增速远超营收
    if b0 and i0:
        ar, ar0 = _n(b.get('应收账款')), _n(b0.get('应收账款'))
        rv, rv0 = _n(i.get('营业总收入')), _n(i0.get('营业总收入'))
        if ar and ar0 and rv and rv0:
            g1, g2 = (ar - ar0) / abs(ar0) * 100, (rv - rv0) / abs(rv0) * 100
            if g1 - g2 >= 20:
                add('medium', '应收账款增速远超营收', '应收 +%.1f%% vs 营收 +%.1f%%，剪刀差 %.1f pct' % (g1, g2, g1 - g2),
                    ['资产负债表: 应收账款', '利润表: 营业总收入'])
    # R4 存货增速远超成本
    if b0 and i0:
        iv, iv0 = _n(b.get('存货')), _n(b0.get('存货'))
        cs, cs0 = _n(i.get('营业成本')), _n(i0.get('营业成本'))
        if iv and iv0 and cs and cs0:
            g1, g2 = (iv - iv0) / abs(iv0) * 100, (cs - cs0) / abs(cs0) * 100
            if g1 - g2 >= 25:
                add('medium', '存货增速远超成本', '存货 +%.1f%% vs 营业成本 +%.1f%%，关注滞销与跌价风险' % (g1, g2),
                    ['资产负债表: 存货', '利润表: 营业成本'])
    # R5 应交税费 / 利润总额 异常
    tp, taxp = _n(i.get('利润总额')), _n(b.get('应交税费'))
    if tp and taxp and tp > 0:
        r = taxp / tp * 100
        if r < 2 or r > 40:
            add('medium', '应交税费与利润总额不匹配', '应交税费/利润总额 = %.1f%%，偏离常态区间' % r,
                ['资产负债表: 应交税费@%s' % d, '利润表: 利润总额@%s' % d])
    # R6 商誉+无形资产 占净资产
    eq = _n(b.get('归母权益合计')) or _n(b.get('所有者权益合计'))
    gw, ia = _n(b.get('商誉')) or 0, _n(b.get('无形资产')) or 0
    if eq and (gw + ia) / eq >= 0.30:
        add('medium', '商誉+无形资产占净资产偏高', '合计占净资产 %.1f%%，减值风险敞口大' % ((gw + ia) / eq * 100),
            ['资产负债表: 商誉/无形资产/归母权益合计'])
    # R7 少数股东损益 与 少数股东权益 错配
    mi_p, mi_e = _n(i.get('少数股东损益')), _n(b.get('少数股东权益'))
    npf = _n(i.get('净利润'))
    if mi_p is not None and mi_e and npf:
        if abs(mi_p / npf) - abs(mi_e / ta) > 0.25 if ta else False:
            add('medium', '少数股东损益与权益错配', '少数股东损益占净利 %.1f%% 但权益占总资产 %.1f%%，结构异常' % (mi_p / npf * 100, mi_e / ta * 100),
                ['利润表: 少数股东损益', '资产负债表: 少数股东权益'])
    # R8 经营现金流/净利润 连续偏低
    weak = 0
    for dd in isd[:4]:
        n2v = _n(_g(is_, dd).get('净利润'))
        o2v = _n(_g(cf, dd).get('经营活动现金流净额'))
        if n2v and n2v > 0 and o2v is not None and o2v / n2v < 0.5:
            weak += 1
    if weak >= 2:
        add('high', '经营现金流持续偏弱', '近 %d 期中 %d 期 净现比 < 0.5，利润变现能力不足' % (min(4, len(isd)), weak),
            ['利润表/现金流量表 近 %d 期' % min(4, len(isd))])
    # R9 非经常性损益占比高
    pnp, dpnp = _n(i.get('归母净利润')), _n(i.get('扣非归母净利润'))
    if pnp and dpnp is not None and pnp != 0:
        r = (pnp - dpnp) / abs(pnp) * 100
        if abs(r) >= 30:
            add('medium', '非经常性损益占比高', '非经常性损益占归母净利 %.1f%%，盈利可持续性存疑' % r,
                ['利润表: 归母净利润/扣非归母净利润@%s' % d])
    # R10 投资活动大额流出但无对应扩张
    iv_ = _n(c.get('投资活动现金流净额'))
    if iv_ is not None and ta and iv_ < 0 and abs(iv_) / ta > 0.25:
        add('low', '投资活动大额净流出', '投资净流出占总资产 %.1f%%，核对投向与回报' % (abs(iv_) / ta * 100),
            ['现金流量表: 投资活动现金流净额@%s' % d])
    order = {'high': 0, 'medium': 1, 'low': 2}
    flags.sort(key=lambda x: order.get(x['level'], 3))
    return flags


def dupont_trend(canon, periods=8):
    bs, is_ = canon['资产负债表'], canon['利润表']
    isd = sorted([x['date'] for x in is_], reverse=True)[:periods]
    out = []
    for d in isd:
        out.append({'period': d, **{k: dupont(canon, d).get(k) for k in ('net_margin', 'asset_turnover', 'equity_multiplier', 'roe')}})
    return list(reversed(out))


def run(canon, ind=None):
    isd = sorted([x['date'] for x in canon['利润表']], reverse=True)
    d = isd[0] if isd else None
    if not d:
        return {'ok': False, 'reason': '无报告期'}
    dup = dupont(canon, d)
    wc = working_capital(canon, d)
    cfp = cashflow_profile(canon, d)
    eq_ = earnings_quality(canon, d)
    tx = tax(canon, d)
    aq = asset_quality(canon, d)
    gt = growth_triangle(canon)
    tr = trend(canon)
    return {'ok': True, 'code': canon.get('code'), 'name': canon.get('name'), 'period': d,
            'dupont': dup, 'working_capital': wc, 'cashflow': cfp, 'earnings_quality': eq_,
            'tax': tx, 'asset_quality': aq, 'growth': gt, 'trend': tr,
            'redflags': redflags(canon, ind), 'dupont_trend': dupont_trend(canon),
            'scorecard': scorecard(dup, wc, cfp, eq_, tx, aq, gt)}
