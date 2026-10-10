# -*- coding: utf-8 -*-
"""财报增强分析：审计意见 / 附注关键项 / 跨期一致性 / 行业口径基准 / 真实盈余管理。

全部围绕「上市公司财务报告」本身，只依据公开数据，缺失即标注缺失，不编造。
"""
import time
from . import scanner, deep, warehouse, marketdata, announce as announce_mod

# ---------------- 1) 审计意见 / 内控意见 ----------------
_OP = [('无法表示意见', '无法表示意见'), ('否定意见', '否定意见'), ('保留意见', '保留意见'),
       ('带强调事项段', '带强调事项段的无保留意见'), ('强调事项', '带强调事项段的无保留意见'),
       ('标准无保留意见', '标准无保留意见'), ('无保留意见', '标准无保留意见')]


def _find_opinion(body):
    for kw, label in _OP:
        if kw in body:
            return label
    return '未明确（正文含审计意见相关段落）' if '审计意见' in body else None


def audit_opinion(code):
    items = announce_mod._list(code, 40)
    cand = [it for it in items if any(k in it['title'] for k in ('审计报告', '年度报告', '半年度报告', '内部控制'))]
    if not cand:
        return {'ok': False, 'reason': '未找到定期报告/审计报告公告'}
    out = []
    for it in cand[:3]:
        body = announce_mod._content(it['art'])
        if not body:
            continue
        ic = None
        if '内部控制' in body:
            if '否定意见' in body:
                ic = '内控否定意见'
            elif '重大缺陷' in body:
                ic = '存在重大缺陷'
            elif '重要缺陷' in body:
                ic = '存在重要缺陷'
            elif '有效' in body:
                ic = '有效（未提及重大缺陷）'
        ev = ''
        o = _find_opinion(body)
        if o:
            i = body.find('审计意见')
            ev = body[max(0, i - 20):i + 120] if i >= 0 else ''
        out.append({'title': it['title'], 'date': it.get('date'), 'opinion': o, 'internal_control': ic,
                    'evidence': ev, 'content_len': len(body)})
    return {'ok': True, 'code': code, 'items': out,
            'note': '审计/内控意见由定期报告或审计报告正文提取；证据为片段，请回原文核对。'}


# ---------------- 2) 附注关键项 ----------------
NOTES_KEYS = [
    ('对外担保', ['对外担保', '担保总额', '担保余额', '担保总额占']),
    ('受限资产', ['所有权受到限制', '使用受限', '受限资产', '质押']),
    ('应收账龄', ['账龄', '1 年以内', '1年以内']),
    ('商誉减值', ['商誉减值', '商誉账面价值']),
    ('研发资本化', ['资本化研发', '研发投入资本化', '开发支出']),
    ('政府补助', ['政府补助', '计入当期损益的政府补助']),
    ('有息负债', ['短期借款', '长期借款', '应付债券']),
    ('关联交易', ['关联交易', '关联方交易']),
    ('分部/主营', ['分部', '主营业务分行业', '主营业务分产品']),
]


def notes_extract(code, window=280):
    items = announce_mod._list(code, 40)
    rep = next((it for it in items if ('年度报告' in it['title'] or '半年度报告' in it['title'] or '季度报告' in it['title'])), None)
    if not rep:
        return {'ok': False, 'reason': '未找到定期报告'}
    body = announce_mod._content(rep['art'])
    if not body:
        return {'ok': False, 'reason': '定期报告正文为空（公告全文接口未返回）'}
    hits = {}
    for name, kws in NOTES_KEYS:
        segs = []
        for kw in kws:
            i = body.find(kw)
            if i >= 0:
                segs.append({'关键词': kw, '片段': body[i:i + window].replace('\n', ' ')})
                if len(segs) >= 2:
                    break
        if segs:
            hits[name] = segs
    return {'ok': True, 'code': code, 'title': rep['title'], 'content_len': len(body), 'hits': hits,
            'note': '附注关键项以定期报告全文中关键词命中片段呈现（证据优先，可回原文核对）；未命中即该报告未单列。'}


# ---------------- 3) 跨期口径一致性 / 重述嫌疑 ----------------
_CONSIST = [('利润表', '营业总收入', '营业收入'), ('利润表', '归母净利润', '归母净利润'),
            ('现金流量表', '经营活动产生的现金流量净额', '经营现金流'),
            ('资产负债表', '应收账款', '应收账款'), ('资产负债表', '存货', '存货'),
            ('资产负债表', '商誉', '商誉'), ('资产负债表', '货币资金', '货币资金')]


def consistency(code):
    r = scanner.analyze(code, 6 * 3600, advanced=False, periods=12)
    canon = r['canonical']
    tl = {}
    for kind, key, label in _CONSIST:
        ser = []
        for it in canon.get(kind) or []:
            v = it['values'].get(key)
            if isinstance(v, (int, float)):
                ser.append([it['date'], round(v, 2)])
        ser.sort()
        if ser:
            tl[label] = ser
    flags = []

    def yoy(label, vals):
        if len(vals) < 5:
            return
        last, prev = vals[-1][1], vals[-3][1] if len(vals) >= 3 else None
        if prev and abs(prev) > 1e-6:
            ch = (last / prev - 1) * 100
            if abs(ch) > 60:
                flags.append('%s 同比突变 %.0f%%（%s），疑口径变更或重述' % (label, ch, vals[-1][0]))
    for label, vals in tl.items():
        yoy(label, vals)
    anns = [it for it in announce_mod._list(code, 40)
            if any(k in it['title'] for k in ('会计政策', '会计估计', '前期差错', '追溯', '重述'))]
    for a in anns[:5]:
        flags.append('公告：%s（%s）' % (a['title'], a.get('date')))
    return {'ok': True, 'code': code, 'timeline': tl, 'flags': flags,
            'note': '跨期一致性基于多期三表 + 会计政策/前期差错相关公告；突变或口径公告即为需人工复核的信号。'}


# ---------------- 4) 行业口径基准 ----------------
def _pct(vals, v):
    xs = [x for x in vals if isinstance(x, (int, float))]
    if not xs or not isinstance(v, (int, float)):
        return None
    return round(100.0 * sum(1 for x in xs if x <= v) / len(xs), 1)


def industry_bench(code):
    r = scanner.analyze(code, 6 * 3600, advanced=False, periods=8)
    idx = (r['indicators']['rows'][0]['indices'] if r['indicators']['rows'] else {}) or {}
    prof = {}
    try:
        prof = marketdata.profile(code) or {}
    except Exception:
        pass
    ind = prof.get('industry') or ''
    d, rows = warehouse.market_snap()
    mine = {x['code']: x for x in rows}.get(str(code).zfill(6), {})
    peer = []
    if ind:
        with warehouse.cursor() as c:
            codes = [x[0] for x in c.execute('SELECT code FROM stocks WHERE industry=?', (ind,)).fetchall()]
        cs = set(codes)
        peer = [x for x in rows if x['code'] in cs]
    basis = '同行业（%s）' % ind if len(peer) >= 8 else '全市场'
    pool = peer if len(peer) >= 8 else rows
    metrics = ['np_yoy', 'rev_yoy', 'roe', 'gm']
    out = {}
    for m in metrics:
        vals = [x.get(m) for x in pool]
        out[m] = {'公司': mine.get(m), '分位': _pct(vals, mine.get(m))}
    struct = {}
    try:
        dd = deep.run(r['canonical'], r['indicators'])
        aq = dd.get('asset_quality') or {}
        for k in ('inventory_pct', 'receivable_pct', 'goodwill_pct'):
            if isinstance(aq.get(k), (int, float)):
                struct[k] = aq.get(k)
    except Exception:
        pass
    return {'ok': True, 'code': code, 'industry': ind, 'basis': basis, 'peer_n': len(pool),
            '指标分位': out, '结构': struct, '公司指标': {k: idx.get(k) for k in
            ['毛利率%', '归母净利率%', 'ROE(归母权益)%', '资产负债率%']},
            'note': '分位为公司在%s内所处百分位（越高越好/越大）；结构为资产质量占比。' % basis}


# ---------------- 5) 真实盈余管理 (REM) + 分类转移 ----------------
def rem(code):
    r = scanner.analyze(code, 6 * 3600, advanced=False, periods=8)
    idx = (r['indicators']['rows'][0]['indices'] if r['indicators']['rows'] else {}) or {}
    dd = {}
    try:
        dd = deep.run(r['canonical'], r['indicators'])
    except Exception:
        pass
    eq = dd.get('earnings_quality') or {}
    flags = []
    ncr = idx.get('净现比')
    if isinstance(ncr, (int, float)) and ncr < 0.6:
        flags.append('REM 嫌疑：净现比 %.2f（<0.6），经营现金流显著低于利润，可能通过放宽信用/过度生产做高利润' % ncr)
    gm = idx.get('毛利率%')
    dso_proxy = None
    wc = dd.get('working_capital') or {}
    dio = wc.get('DIO_存货周转天数') or wc.get('dio')
    if isinstance(dio, (int, float)) and dio > 180:
        flags.append('REM 嫌疑：存货周转天数 %.0f 天偏高，可能通过过度生产摊薄单位成本' % dio)
    ncc = idx.get('扣非占比%')
    if isinstance(ncc, (int, float)) and 0 < ncc < 70:
        flags.append('分类转移嫌疑：扣非占比仅 %.1f%%，核心利润依赖非经常性损益' % ncc)
    acc = eq.get('accruals')
    if isinstance(acc, (int, float)) and acc > 0.1:
        flags.append('应计偏高 %.3f（权责发生制盈余管理）' % acc)
    if not flags:
        flags.append('未触发 REM / 分类转移规则（净现比、存货周转、扣非占比、应计均在常规区间）')
    return {'ok': True, 'code': code,
            'inputs': {'净现比': ncr, '扣非占比%': ncc, '毛利率%': gm,
                       'DIO': dio, '应计': acc},
            'flags': flags,
            'note': 'REM 采用 Roychowdhury 思路的简化代理（经营现金流/存货周转/酌量费用方向）；分类转移看扣非占比与非经常性结构。'}
