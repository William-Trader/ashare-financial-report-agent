# -*- coding: utf-8 -*-
"""投资逻辑闭环：事实基线 -> 核心假设 -> 验证/反证 -> 估值与边际 -> 风险与证伪 -> 跟踪触发。
用推理档模型（deepseek-reasoner）做深度推演，输出结构化 + 可执行。"""
import json
from . import llm, scanner, deep, valuation, events as events_mod, marketdata, caliber

SYS = ('你是卖方/买方通用的 A 股财报分析师，做的是**投资逻辑闭环**，不是复述数据。'
       '只依据我给的 JSON 事实，禁止编造任何数字或事件；每条关键结论后用【依据：字段@期间】标注来源。'
       '必须区分【事实】与【推论】，并给出可操作的**证伪条件**（什么情况说明这个判断错了）。'
       '输出简洁中文，结构如下（用 Markdown 小标题）：\n'
       '**一句话倾向**（含 关注/谨慎/规避 + 核心逻辑一句）\n'
       '**1 事实基线**（3-5 条最关键数据）\n'
       '**2 核心假设**（2-3 条，必须可验证）\n'
       '**3 验证与反证**（逐条给支持证据与反证信号）\n'
       '**4 估值与安全边际**（结合估值分位与盈利质量）\n'
       '**5 主要风险与证伪条件**（可操作）\n'
       '**6 跟踪触发**（何时/看到什么就该复核）\n'
       '全文 600 字以内。')


def gather(code):
    r = scanner.analyze(code, 6 * 3600, advanced=True, periods=8)
    rep = r['report']
    inc = r['indicators']['rows'][0]['indices'] if r['indicators']['rows'] else {}
    keep = ('毛利率%', '归母净利率%', 'ROE(归母权益)%', '资产负债率%', '净现比', '收现比', '扣非占比%',
            '单季营收同比%', '单季归母净利同比%', '单季经营现金流同比%')
    facts = {
        'code': rep.get('code'), 'name': rep.get('name'), 'period': rep.get('period'),
        '指标': {k: inc.get(k) for k in keep},
        '勾稽校验': rep.get('checks_summary'),
        '异常信号': [{'类别': a['category'], '期间': a['period'], '等级': a['level'], '说明': a['title']} for a in (r.get('anomalies') or [])[:6]],
        '风险': {'分数': (r.get('risk') or {}).get('score'), '等级': (r.get('risk') or {}).get('level'),
                 '驱动': [d['name'] for d in ((r.get('risk') or {}).get('drivers') or [])[:5]]},
        '归因': [a.get('text') for a in (rep.get('attribution') or [])],
    }
    try:
        fp = marketdata.profile(code)
        facts['行业'] = fp.get('industry')
    except Exception:
        pass
    try:
        d = deep.run(r['canonical'], r['indicators'])
        facts['深析'] = {'杜邦': d.get('dupont'), '现金流形态': (d.get('cashflow') or {}).get('label'),
                         'FCF利润率': (d.get('cashflow') or {}).get('fcf_margin'),
                         '盈利质量': d.get('earnings_quality'), '成长一致性': (d.get('growth') or {}).get('consistency'),
                         '评分卡': {k: (d.get('scorecard') or {}).get(k) for k in ('score', 'grade')},
                         '红旗': [f.get('name') for f in (d.get('redflags') or [])]}
    except Exception:
        pass
    try:
        v = valuation.run(code)
        facts['估值'] = {'pe': v.get('pe'), 'pe_percentile': v.get('pe_percentile'),
                         'pb': v.get('pb'), 'pb_percentile': v.get('pb_percentile'),
                         'price_percentile': v.get('price_percentile')}
    except Exception:
        pass
    try:
        ev = events_mod.all_events(code)
        facts['事件'] = [{'日期': i.get('date'), '类型': i.get('source'), '内容': (i.get('title') or i.get('reason') or '')[:80]}
                         for i in (ev.get('items') or [])[:8]]
    except Exception:
        pass
    return facts


def run(code, use_deep=True, with_caliber=True):
    facts = gather(code)
    if with_caliber:
        try:
            r0 = scanner.analyze(code, 6 * 3600, advanced=False, periods=8)
            c = caliber.run(r0['canonical'], r0['indicators'], (facts.get('行业') or ''))
            facts['口径守卫'] = {'边界风险': c.get('boundary_risk'),
                                 '告警': [w['说明'] for w in (c.get('warnings') or [])[:5]]}
        except Exception:
            pass
    msg = [{'role': 'system', 'content': SYS},
           {'role': 'user', 'content': '以下是该公司的结构化事实（JSON）：\n' + json.dumps(facts, ensure_ascii=False, default=str)[:9000]}]
    res = llm.chat(msg, temperature=0.2, max_tokens=1600, timeout=180, deep=use_deep)
    out = {'ok': bool(res.get('ok')), 'code': facts.get('code'), 'name': facts.get('name'),
           'period': facts.get('period'), 'model': res.get('model'), 'facts': facts,
           'thesis': res.get('text') or '', 'error': res.get('error')}
    return out
