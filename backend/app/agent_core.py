# -*- coding: utf-8 -*-
"""独立 agent 核心（不依赖 OpenClaw）：LLM + 工具 的函数调用循环。

这就是「financial report claw」的智能体引擎——它自己决定调哪个财报工具、自己组织结论。
"""
import json, threading
from . import llm, scanner, suggest as suggest_mod, deep, realtime as rt, market, screener as screener_mod
from . import announce as announce_mod, caliber, valuation_model, events as events_mod, warehouse

SYS = ('你是「financial report claw」——一位顶级 A 股财报分析师，独立自持，一切结论用工具取到的真实数据说话。\n'
       '【铁律】只依据工具返回的事实，绝不编造数字；数据不足就直说；关键数字带出处【依据：字段@期间】。\n'
       '【怎么答才配得上“顶级”】\n'
       '1) 先判断、后证据：开门见山给出立场（好 / 坏 / 危险 / 被低估 / 被高估），再用数据支撑——不要先罗列一堆数字最后才挤出一句结论。\n'
       '2) 每个判断都要有观点：不做无立场的复述。该说“这份财报有问题”就说，该说“数据不足以下结论”也说。\n'
       '3) 主动指出别人容易漏的点：会计口径/结构变化、利润与现金流背离、非经常性损益撑起利润、应收/存货/商誉异常、一次性收益、分红与回购。\n'
       '4) 主动给对比与下一步：与同行/历史/另一家公司比（用 peer_benchmark），并给可执行的下一步或跟踪触发点。\n'
       '5) 复杂问题先多调几个工具（analyze + deep_analysis + quote + peer_benchmark / thesis）再综合，别拿单一工具的输出了事。\n'
       '【风格随问题变】简单指标/价格 → 一两句直答；需要判断的分析 → 自然分「判断 / 依据 / 风险 / 操作」，不必逐条套同一骨架；闲聊 → 自然对话。\n'
       '【自我纠正】用户说你错 / 让改 / 给新信息时，重新调工具核对再纠正，绝不固执重复。\n'
       '【多轮】保持上下文：用户说「它」「这家」「那它呢」时结合上文公司。\n'
       '【周期股时序纪律】凡周期股/重资产股（有色/黄金/煤炭/钢铁/石油/化工/建材/采矿等），下结论前必须同轮同时调用 analyze + deep_analysis 交叉核对，浅深不一致时以 deep_analysis 为准；可调 cyclical 做量价拆分/情景压力测试/科目穿透/异常三级定性；禁止先浅后深、说一半改一半。\n'
       '结尾一行：仅供参考，不构成投资建议。')

MAX_ITER = 6


def _tool_analyze(code):
    r = scanner.analyze(code, 6 * 3600, advanced=True, periods=6)
    rep = r['report']
    inc = r['indicators']['rows'][0]['indices'] if r['indicators']['rows'] else {}
    keep = ['毛利率%', '归母净利率%', 'ROE(归母权益)%', '资产负债率%', '净现比', '收现比', '扣非占比%',
            '单季营收同比%', '单季归母净利同比%', '单季经营现金流同比%']
    return {'name': rep.get('name'), 'period': rep.get('period'),
            '指标': {k: inc.get(k) for k in keep},
            '勾稽校验': rep.get('checks_summary'),
            '风险': {'分数': (r.get('risk') or {}).get('score'), '等级': (r.get('risk') or {}).get('level'),
                     '驱动': [d['name'] for d in ((r.get('risk') or {}).get('drivers') or [])[:5]]},
            '异常': [{'类别': a['category'], '期间': a['period'], '说明': a['title']} for a in (r.get('anomalies') or [])[:6]],
            '建议': suggest_mod.build(r, with_llm=False).get('conclusion_text')}


def _tool_deep(code):
    r = scanner.analyze(code, 6 * 3600, advanced=False, periods=8)
    d = deep.run(r['canonical'], r['indicators'])
    return {'杜邦': d.get('dupont'), '现金流形态': (d.get('cashflow') or {}).get('label'),
            'FCF利润率': (d.get('cashflow') or {}).get('fcf_margin'),
            '盈利质量': d.get('earnings_quality'), '税负': d.get('tax'),
            '资产质量': d.get('asset_quality'), '成长一致性': (d.get('growth') or {}).get('consistency'),
            '评分卡': {k: (d.get('scorecard') or {}).get(k) for k in ('score', 'grade')},
            '红旗': [f.get('name') for f in (d.get('redflags') or [])]}


def _tool_quote(code):
    q = rt.quote(code)
    if not q.get('ok'):
        return {'error': q.get('error')}
    return {'名称': q.get('name'), '价格': q.get('price'), '涨跌%': q.get('changePct'),
            'PE': q.get('pe'), 'PB': q.get('pb'), '总市值': q.get('marketCap'), '换手%': q.get('turnoverPct')}


def _tool_market():
    try:
        d = market.digest(market.latest_period())
    except Exception:
        d = market.digest()
    if not d.get('text'):
        return {'error': '市场摘要暂不可用'}
    return {'报告期': d.get('date'), '统计': d.get('stats'), '板块': (d.get('board') or [])[:6], '摘要': d.get('text')}


def _tool_screen(criteria):
    kw = {}
    for k, key in (('ROE', 'min_roe'), ('净利', 'min_np_yoy'), ('营收', 'min_rev_yoy'), ('毛利', 'min_gm')):
        import re
        m = re.search(k + r'\\s*[>≥]\\s*([\\d.]+)', criteria or '')
        if m:
            kw[key] = float(m.group(1))
    r = screener_mod.run(None, kw.get('min_np_yoy'), kw.get('min_rev_yoy'), kw.get('min_roe'), kw.get('min_gm'),
                         None, None, ['亏损', '净利暴雷'], [], 'score', 10)
    if not r.get('ok'):
        return {'error': r.get('reason')}
    return {'命中': r.get('matched'), '前10': [{'名称': x['name'], '代码': x['code'], '分': x['score'],
                                               '净利同比': x['np_yoy'], 'ROE': x['roe']} for x in r.get('items', [])[:10]]}


def _tool_announce(code):
    a = announce_mod.run(code, 20, 3, use_llm=False)
    return {'分类': a.get('categories'),
            '最近': [{'日期': i['date'], '标题': i['title'], '类': i['cats']} for i in a.get('items', [])[:10]]}


def _tool_caliber(code):
    r = scanner.analyze(code, 6 * 3600, advanced=False, periods=8)
    ind = ''
    try:
        ind = (__import__('app.marketdata', fromlist=['x']).profile(code) or {}).get('industry') or ''
    except Exception:
        pass
    c = caliber.run(r['canonical'], r['indicators'], ind)
    return {'边界风险': c.get('boundary_risk'), '告警': [w['说明'] for w in (c.get('warnings') or [])[:5]]}


def _tool_valuation(code):
    v = valuation_model.run(code)
    if not v.get('ok'):
        return {'error': v.get('reason')}
    return {'DCF每股': (v.get('dcf') or {}).get('base', {}).get('per_share'),
            '区间': [(v.get('dcf') or {}).get('low'), (v.get('dcf') or {}).get('high')],
            '现价': (v.get('verdict') or {}).get('price'), '较基准%': (v.get('verdict') or {}).get('vs_base'),
            '相对估值': v.get('relative')}


def _tool_events(code):
    e = events_mod.all_events(code)
    return {'最近': [{'日期': i.get('date'), '类型': i.get('source'), '内容': (i.get('title') or i.get('reason') or '')[:60]}
                     for i in (e.get('items') or [])[:8]]}


def _tool_peer(code):
    from . import research
    p = research.peer(code)
    if not p.get('ok'):
        return {'note': p.get('reason')}
    return {'赛道': p.get('track_name'), '同业家数': p.get('peer_count'),
            '分位': {k: (v or {}).get('分位') for k, v in (p.get('ranks') or {}).items()},
            '同业中位': {k: (v or {}).get('同业中位') for k, v in (p.get('ranks') or {}).items()},
            '同赛道高风险': [x.get('name') for x in (p.get('top_risk_peers') or [])[:6]]}


def _tool_checkup(code):
    from . import checkup
    r = scanner.analyze(code, 6 * 3600, advanced=False, periods=8)
    c = checkup.run(r['canonical'], r['indicators'])
    if not c.get('ok'):
        return {'error': c.get('reason')}
    return {'质量分': c.get('score'), '评级': c.get('grade'), '报告期': c.get('period'),
            '结构': (c.get('structure') or [])[:6], '同比变动': (c.get('yoy') or [])[:6]}


def _tool_thesis(code):
    from . import thesis
    t = thesis.run(code, use_deep=False, with_caliber=True)
    if not isinstance(t, dict) or not t.get('ok', True):
        return {'error': (t or {}).get('reason') if isinstance(t, dict) else 'unavailable'}
    return t


def _tool_dividend(code):
    from . import dividend as dv
    d = dv.run(code)
    items = d.get('items') or []
    return {'近期分红': [{'日期': x.get('date'), '方案': x.get('plan'), '总额': x.get('total')} for x in items[:5]]}


def _tool_fundflow(code):
    f = rt.fundflow(code, 10)
    items = f.get('items') or []
    return {'近日主力净流入': items[-5:]}


def _tool_cyclical(code):
    from . import cyclical
    r = cyclical.run(code)
    tr = r.get('triage') or {}
    st = r.get('stress_test') or {}
    gi = r.get('goodwill_intangibles') or {}
    return {'name': r.get('name'), 'period': r.get('period'), 'industry': r.get('industry'), 'cyclical': r.get('cyclical'),
            '异常三级定性': tr.get('counts'),
            '情景压力测试_净利变动%': {str(x.get('shock_pct')): x.get('net_profit_pct') for x in (st.get('rows') or [])},
            '量价拆分': {k: (r.get('price_volume_split') or {}).get(k) for k in ('rev_growth_pct', 'np_growth_pct', 'price_driven_pct', 'volume_driven_pct', 'margin_and_other_pp', 'price_volume_note')},
            '科目穿透': {k: gi.get(k) for k in ('goodwill_pct_equity', 'goodwill_flag', 'impairment_flag')}}





def _tool_capital(code):
    from . import capital
    c = capital.run(code)
    if not c.get('ok'):
        return {'error': c.get('reason')}
    if not c.get('applicable', True):
        return {'note': c.get('reason'), 'industry': c.get('industry')}
    return {'name': c.get('name'), 'period': c.get('period'), 'industry': c.get('industry'),
            'ROIC年化%': c.get('roic_annual_pct'), 'ROE年化%': c.get('roe_annual_pct'),
            'WACC%': round((c.get('wacc') or 0) * 100, 2), '价差pp': c.get('spread_pct'),
            'EVA亿元': c.get('eva_annual_yi'), 'NOPAT率%': c.get('nopat_margin_pct'),
            '资本周转': c.get('capital_turnover_annual'), '投入资本亿元': (c.get('inputs') or {}).get('invested_capital_yi'),
            '判读': (c.get('verdict') or {}).get('level'), '结论': (c.get('verdict') or {}).get('read'),
            '提示': [f.get('name') for f in (c.get('flags') or [])]}

TOOLS = [
    {'type': 'function', 'function': {'name': 'analyze', 'description': '分析一家公司财报：三表+指标+勾稽+异常+风险+建议', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string', 'description': '6位股票代码'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'deep_analysis', 'description': '财报深析：杜邦/周转/现金流形态/盈利质量/税负/资产质量/评分卡/红旗', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'quote', 'description': '实时行情（价/涨跌/PE/PB/市值）', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'market_overview', 'description': '全市场异动摘要', 'parameters': {'type': 'object', 'properties': {}}}},
    {'type': 'function', 'function': {'name': 'screen', 'description': '全市场选股，criteria 如 "ROE>15 净利>0"', 'parameters': {'type': 'object', 'properties': {'criteria': {'type': 'string'}}, 'required': ['criteria']}}},
    {'type': 'function', 'function': {'name': 'announcements', 'description': '公司公告分类（会计政策变更/回购/质押等）', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'caliber_check', 'description': '口径守卫：金融股/中期未年化等边界告警', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'valuation', 'description': '估值建模：DCF+相对估值+敏感性区间', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'events', 'description': '公司事件流（龙虎榜/两融/大宗/公告/业绩预告）', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'peer_benchmark', 'description': '赛道对标：公司在同赛道内的关键指标分位（ROE/毛利率/净现比/同比）', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'checkup', 'description': '财报体检：质量分 + 科目结构 + 同比变动', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'thesis', 'description': '投资逻辑闭环：事实基线/核心假设/验证与反证/证伪条件/跟踪触发', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'dividend', 'description': '分红历史', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'fundflow', 'description': '近期主力资金净流入', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'cyclical', 'description': '周期股专项：量价拆分/情景压力测试/科目穿透/异常三级定性（有色/煤炭/钢铁/石油/化工/建材/采矿等重资产）', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
    {'type': 'function', 'function': {'name': 'capital', 'description': '资本回报与价值创造：ROIC/WACC/EVA 价差、投入资本回报拆解、ROE-ROIC 杠杆差（非金融企业）', 'parameters': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}}},
]

DISPATCH = {
    'analyze': lambda a: _tool_analyze(a.get('code')),
    'deep_analysis': lambda a: _tool_deep(a.get('code')),
    'quote': lambda a: _tool_quote(a.get('code')),
    'market_overview': lambda a: _tool_market(),
    'screen': lambda a: _tool_screen(a.get('criteria')),
    'announcements': lambda a: _tool_announce(a.get('code')),
    'caliber_check': lambda a: _tool_caliber(a.get('code')),
    'valuation': lambda a: _tool_valuation(a.get('code')),
    'events': lambda a: _tool_events(a.get('code')),
    'peer_benchmark': lambda a: _tool_peer(a.get('code')),
    'checkup': lambda a: _tool_checkup(a.get('code')),
    'thesis': lambda a: _tool_thesis(a.get('code')),
    'dividend': lambda a: _tool_dividend(a.get('code')),
    'fundflow': lambda a: _tool_fundflow(a.get('code')),
    'cyclical': lambda a: _tool_cyclical(a.get('code')),
    'capital': lambda a: _tool_capital(a.get('code')),
}


SIMPLE_HINTS = ('多少', '是什么', '啥', '几倍', '价格', '股价', '现价', '市值', '行情', 'pe', 'pb',
                '净现比', '毛利率', '净利率', 'roe', '资产负债率', '扣非', '收现比', '分红', '换手')
DEEP_HINTS = ('分析', '值得', '风险', '对比', '比较', '为什么', '怎么样', '如何', '估值', '深析', '体检',
              '逻辑', '看好', '前景', '诊断', '点评', '该不该', '能不能买', '财报怎么样', '靠谱', '有问题', '回报', '效率', '杠杆')


def _pick_deep(text):
    """问题复杂度路由：简单取数 → chat 快路径；需要判断 → v4-pro 深档。"""
    t = (text or '').strip()
    tl = t.lower()
    if any(k in tl for k in DEEP_HINTS):
        return True
    if any(k in tl for k in SIMPLE_HINTS) and len(t) <= 16:
        return False
    return len(t) > 16


def ask(text, session_key=None, use_deep=None):
    if use_deep is None:
        use_deep = _pick_deep(text)
    key = session_key or 'default'
    with _HIST_LOCK:
        hist = list(_HIST.get(key) or [])
    msgs = [{'role': 'system', 'content': SYS}] + hist[-8:] + [{'role': 'user', 'content': text}]
    before = len(_STATS)
    for _ in range(MAX_ITER):
        res = llm.chat_tools(msgs, TOOLS, deep=use_deep)
        if not res.get('ok'):
            return {'ok': False, 'error': res.get('error'), 'text': ''}
        if not res.get('tool_calls'):
            ans = res.get('text') or '（无输出）'
            _remember(key, text, ans)
            return {'ok': True, 'text': ans, 'model': res.get('model'), 'tier': ('deep' if use_deep else 'fast'), 'tools_used': _STATS[before:]}
        msgs.append(res['message'])
        for tc in res['tool_calls']:
            fn = tc['function']['name']
            try:
                args = json.loads(tc['function'].get('arguments') or '{}')
            except Exception:
                args = {}
            try:
                out = DISPATCH.get(fn, lambda a: {'error': '未知工具'})(args)
            except Exception as e:
                out = {'error': str(e)[:200]}
            _STATS.append(fn)
            msgs.append({'role': 'tool', 'tool_call_id': tc.get('id'), 'content': json.dumps(out, ensure_ascii=False, default=str)[:3000]})
    ans = '（多次工具调用后仍未给出结论）'
    _remember(key, text, ans)
    return {'ok': True, 'text': ans, 'model': 'loop-limit', 'tools_used': _STATS[before:]}


_HIST = {}
_HIST_LOCK = threading.Lock()


def _remember(key, user_text, answer):
    with _HIST_LOCK:
        h = list(_HIST.get(key) or [])
        h.append({'role': 'user', 'content': user_text[:500]})
        h.append({'role': 'assistant', 'content': (answer or '')[:1500]})
        _HIST[key] = h[-12:]


def reset(session_key=None):
    with _HIST_LOCK:
        _HIST.pop(session_key or 'default', None)
    return {'ok': True, 'sessions': len(_HIST)}


_STATS = []


def stats():
    return {'calls': len(_STATS), 'tools_used': _STATS[-20:]}
