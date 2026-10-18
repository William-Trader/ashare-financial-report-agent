# -*- coding: utf-8 -*-
"""资本回报与价值创造（机构级）：ROIC / WACC / EVA / 投入资本回报拆解。

补上杜邦(ROE)之外的"资金效率"视角：ROE 高不等于创造价值——只有 ROIC 高于资本成本
(WACC) 才真正为股东创造价值。全部由三表口径自算；缺数据诚实标注，不编。
"""
from .normalize import find_period
from . import scanner as _scanner

FIN_KW = ('银行', '保险', '证券', '信托', '多元金融')
DAYS = {'03': 90, '06': 181, '09': 273, '12': 365}


def _n(v):
    return v if isinstance(v, (int, float)) else None


def _g(stmt, d):
    it = find_period(stmt, d)
    return it['values'] if it else {}


def _period_days(d):
    return DAYS.get((d or '')[5:7], 365)


def _interest_debt(b):
    return sum([(_n(b.get(k)) or 0) for k in
                ('短期借款', '长期借款', '一年内到期的非流动负债', '应付债券', '租赁负债')])


def _equity(b):
    e = _n(b.get('所有者权益合计'))
    if e is None:
        e = (_n(b.get('归母权益合计')) or 0) + (_n(b.get('少数股东权益')) or 0)
    return e


def _ebit(i):
    tp = _n(i.get('利润总额'))
    if tp is None:
        return None
    ie = _n(i.get('利息费用'))
    if ie is None:
        fe = _n(i.get('财务费用'))
        ie = fe if (fe is not None and fe > 0) else 0.0
    return tp + ie


def _core(bs, is_, d, d_prev):
    """单个报告期的 ROIC 骨架；缺关键科目返回 None。"""
    b = _g(bs, d)
    i = _g(is_, d)
    if not b or not i:
        return None
    ib = _interest_debt(b)
    eq = _equity(b)
    cash = _n(b.get('货币资金')) or 0
    if eq is None:
        return None
    ic_end = ib + eq - cash
    if ic_end <= 0:
        return None
    ic_beg = None
    if d_prev:
        b0 = _g(bs, d_prev)
        if b0:
            e0 = _equity(b0)
            if e0 is not None:
                t0 = _interest_debt(b0) + e0 - (_n(b0.get('货币资金')) or 0)
                ic_beg = t0 if t0 > 0 else None
    ic = (ic_end + ic_beg) / 2.0 if ic_beg else ic_end
    ebit = _ebit(i)
    if ebit is None or ic <= 0:
        return None
    tp = _n(i.get('利润总额'))
    tax = _n(i.get('所得税费用'))
    if tp and tp > 0 and tax is not None:
        tr = max(0.0, min(0.5, tax / tp))
        tr_src = '实际税率(所得税/利润总额)'
    else:
        tr = 0.15
        tr_src = '利润总额<=0或缺失，按15%名义税率'
    nopat = ebit * (1 - tr)
    rev = _n(i.get('营业总收入'))
    if rev is None:
        rev = _n(i.get('营业收入'))
    days = _period_days(d)
    ann = 365.0 / days
    roic_p = nopat / ic
    roic_a = roic_p * ann
    return {'period': d, 'ic': ic, 'ic_end': ic_end, 'interest_debt': ib, 'equity': eq, 'cash': cash,
            'ebit': ebit, 'tax_rate': tr, 'tax_src': tr_src, 'nopat': nopat, 'revenue': rev,
            'roic_period': roic_p, 'roic_annual': roic_a, 'days': days, 'ann': ann,
            'capital_turnover_annual': (rev * ann / ic) if rev else None,
            'nopat_margin': (nopat / rev) if rev else None}


def _roe(bs, is_, d, d_prev):
    i, b, b0 = _g(is_, d), _g(bs, d), (_g(bs, d_prev) if d_prev else {})
    np_ = _n(i.get('归母净利润'))
    if np_ is None:
        np_ = _n(i.get('净利润'))
    pe_now = _n(b.get('归母权益合计'))
    if pe_now is None or np_ is None:
        return None
    pe0 = _n(b0.get('归母权益合计')) if b0 else None
    pe_avg = (pe_now + pe0) / 2.0 if pe0 else pe_now
    if not pe_avg or pe_avg <= 0:
        return None
    return (np_ / pe_avg) * (365.0 / _period_days(d))


def run(code, wacc=0.09):
    code = (code or '').strip()
    try:
        r = _scanner.analyze(code, 6 * 3600, advanced=False, periods=16)
    except Exception as e:
        return {'ok': False, 'reason': '分析失败: ' + str(e)[:120]}
    canon = r['canonical']
    bs, is_ = canon['资产负债表'], canon['利润表']
    bsd = sorted([x['date'] for x in bs], reverse=True)
    if not bsd:
        return {'ok': False, 'reason': '缺少资产负债表数据'}
    industry = ''
    try:
        from . import marketdata
        industry = (marketdata.profile(code) or {}).get('industry') or ''
    except Exception:
        industry = ''
    if any(k in (industry or '') for k in FIN_KW):
        return {'ok': True, 'applicable': False, 'code': canon.get('code'), 'name': canon.get('name'),
                'industry': industry,
                'reason': '金融行业（' + industry + '）的"有息负债/投入资本"口径与实体企业不可比'
                          '（存款即负债、无营业成本概念），ROIC/EVA 不适用；应改用 ROE/ROA 与净息差类指标。',
                'note': '本模块仅对非金融企业计算 ROIC/EVA。'}
    d = bsd[0]
    d_prev = bsd[1] if len(bsd) > 1 else None
    core = _core(bs, is_, d, d_prev)
    if core is None:
        return {'ok': False, 'reason': '缺投入资本/利润总额等关键科目，无法计算 ROIC'}
    roe_a = _roe(bs, is_, d, d_prev)
    spread = core['roic_annual'] - wacc
    ic = core['ic']
    eva_annual = spread * ic
    # 趋势（最多 8 期，按时间正序）
    trend = []
    for idx, dd in enumerate(bsd[:8]):
        prev = bsd[idx + 1] if idx + 1 < len(bsd) else None
        c = _core(bs, is_, dd, prev)
        if c:
            trend.append({'period': dd, 'roic_annual': round(c['roic_annual'] * 100, 2),
                          'roic_period': round(c['roic_period'] * 100, 2), 'ic_yi': round(c['ic'] / 1e8, 2)})
    trend = list(reversed(trend))
    # 判读
    if spread >= 0.03:
        level, sev = '创造价值', '低'
        read = 'ROIC 高于资本成本 %.1fpp，经营在真实创造价值。' % (spread * 100)
    elif spread >= -0.01:
        level, sev = '大致持平', '中'
        read = 'ROIC 与资本成本基本相当（价差 %.1fpp），尚未明显创造或损毁价值。' % (spread * 100)
    else:
        level, sev = '毁灭价值', '高'
        read = 'ROIC 低于资本成本 %.1fpp，扩张可能在毁灭价值——每投入一元都在减损股东财富。' % (-spread * 100)
    flags = []
    if roe_a is not None and (roe_a - core['roic_annual']) > 0.08:
        flags.append({'level': '需核实', 'name': '杠杆依赖回报',
                      'detail': '年化 ROE %.1f%% 高出 ROIC %.1fpp，股东回报主要靠负债放大而非经营效率，需看负债可持续性。'
                                % (roe_a * 100, (roe_a - core['roic_annual']) * 100)})
    if len(trend) >= 3:
        r3 = [x['roic_annual'] for x in trend[-3:]]
        if r3[0] > r3[1] > r3[2]:
            flags.append({'level': '需核实', 'name': 'ROIC 连续下滑',
                          'detail': '近三期年化 ROIC 逐期走低：' + ' → '.join(['%.2f%%' % x for x in r3]) + '，资金效率在退化。'})
    if core['interest_debt'] > 0 and core['interest_debt'] / ic > 0.4:
        flags.append({'level': '需核实', 'name': '有息负债占比偏高',
                      'detail': '有息负债占投入资本 %.1f%%，资本结构对利率与再融资敏感。' % (core['interest_debt'] / ic * 100)})
    if spread <= -0.01:
        flags.append({'level': 'danger', 'name': '回报低于资本成本',
                      'detail': '年化 ROIC %.2f%% < WACC %.2f%%，该项投资在减损价值。' % (core['roic_annual'] * 100, wacc * 100)})
    note = ('ROIC = NOPAT / 平均投入资本；NOPAT = EBIT×(1−实际税率)；投入资本 = 有息负债 + 全部股东权益 − 货币资金；'
            'WACC 为假设值（默认 9%，可用 wacc= 覆盖）。')
    if (d or '')[5:7] != '12':
        note += ' 中期口径：ROIC 已按报告期天数年化，未做季节性调整（累计口径），与年报横比时注意季节性。'
    return {'ok': True, 'applicable': True, 'code': canon.get('code'), 'name': canon.get('name'),
            'industry': industry, 'period': d, 'wacc': wacc, 'wacc_src': '默认资本成本 9%（端点 wacc= 可覆盖）',
            'inputs': {'invested_capital_yi': round(ic / 1e8, 2), 'invested_capital_end_yi': round(core['ic_end'] / 1e8, 2),
                       'interest_debt_yi': round(core['interest_debt'] / 1e8, 2), 'equity_yi': round(core['equity'] / 1e8, 2),
                       'cash_yi': round(core['cash'] / 1e8, 2), 'ebit_yi': round(core['ebit'] / 1e8, 2),
                       'nopat_yi': round(core['nopat'] / 1e8, 2), 'tax_rate': round(core['tax_rate'] * 100, 1),
                       'tax_src': core['tax_src']},
            'roic_period_pct': round(core['roic_period'] * 100, 2),
            'roic_annual_pct': round(core['roic_annual'] * 100, 2),
            'roe_annual_pct': (round(roe_a * 100, 2) if roe_a is not None else None),
            'nopat_margin_pct': (round(core['nopat_margin'] * 100, 2) if core['nopat_margin'] is not None else None),
            'capital_turnover_annual': (round(core['capital_turnover_annual'], 3) if core['capital_turnover_annual'] is not None else None),
            'spread_pct': round(spread * 100, 2),
            'eva_annual_yi': round(eva_annual / 1e8, 2),
            'rose_roic_gap_pp': (round((roe_a - core['roic_annual']) * 100, 2) if roe_a is not None else None),
            'trend': trend,
            'verdict': {'level': level, 'severity': sev, 'read': read},
            'flags': flags,
            'note': note + ' 本模块为研究用途，不构成投资建议。'}
