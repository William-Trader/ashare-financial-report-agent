# -*- coding: utf-8 -*-
"""财报圆桌：五位财报分析师各取一段财报切片，串行 LLM 推演，主持人对决。

角色全部围绕财报本身：财务质量 / 成长景气 / 资产质量 / 估值 / 风控官（可否决）。
"""
import json
from . import llm, scanner, deep, realtime as rt, valuation_model

SYS = ('你是 A 股财报圆桌的一位分析师。只依据给你的 JSON 事实发言，禁止编造数字；'
       '发言要具体、有观点，指出该维度最关键的 2-3 点，关键数字标【依据：字段@期间】。3-5 句，简体中文。')

ROLES = [
    ('财务质量官', '只谈盈利质量与现金流：净现比、扣非占比、应计比率、非经常性损益、现金流形态；判断利润含金量'),
    ('成长景气官', '只谈成长与趋势：单季营收/归母净利/经营现金流同比、成长一致性；判断是加速、见顶还是背离'),
    ('资产质量官', '只谈资产质量与营运：应收/存货/商誉/无形占比、周转与现金周期、杜邦三因子；判断资产是否虚胖、周转是否恶化'),
    ('估值官', '只谈估值：PE/PB 与历史分位、DCF 区间与市价、安全边际；判断贵还是便宜'),
    ('风控官', '审阅风险评分、红旗规则、异常信号与勾稽校验；判断是否有硬伤，给出 通过 / 降级 / 一票否决'),
]

NV = lambda x: x if isinstance(x, (int, float)) else None


def _idx(r):
    rows = (r.get('indicators') or {}).get('rows') or []
    return dict(rows[0].get('indices') or {}) if rows else {}


def _pick(src, keys):
    if not isinstance(src, dict):
        return {}
    return {k: src.get(k) for k in keys if src.get(k) is not None}


def _slices(code):
    r = scanner.analyze(code, 6 * 3600, advanced=True, periods=8)
    d = deep.run(r['canonical'], r['indicators'])
    idx = _idx(r)
    q = rt.quote(code)
    try:
        v = valuation_model.run(code) or {}
    except Exception:
        v = {}
    quote = {k: q.get(k) for k in ('price', 'changePct', 'pe', 'pb', 'marketCap')} if q.get('ok') else {'note': '行情不可用'}
    dcf = (v.get('dcf') or {})
    return {
        '财务质量官': {'核心': _pick(idx, ['毛利率%', '归母净利率%', 'ROE(归母权益)%', '扣非占比%', '净现比', '收现比']),
                      '现金流形态': d.get('cashflow'), '盈利质量': d.get('earnings_quality'), '税负': d.get('tax')},
        '成长景气官': {'单季同比': _pick(idx, ['单季营收同比%', '单季归母净利同比%', '单季经营现金流同比%']),
                      '成长一致性': d.get('growth'), '趋势': d.get('trend'), '杜邦趋势': d.get('dupont_trend')},
        '资产质量官': {'资产质量': d.get('asset_quality'), '营运资本': d.get('working_capital'), '杜邦': d.get('dupont')},
        '估值官': {'行情': quote, 'DCF每股': (dcf.get('base') or {}).get('per_share'),
                  'DCF区间': [dcf.get('low'), dcf.get('high')], '相对估值': v.get('relative'), '结论': v.get('verdict')},
        '风控官': {'风险': r.get('risk'), '红旗': d.get('redflags'), '异常': (r.get('anomalies') or [])[:6],
                  '勾稽': (r.get('report') or {}).get('checks_summary'), '评分卡': d.get('scorecard')},
    }


def run(code, max_tokens=650):
    name = (scanner.analyze(code, 6 * 3600, advanced=False, periods=2).get('report') or {}).get('name') or code
    try:
        sl = _slices(code)
    except Exception as e:
        return {'ok': False, 'error': '取数失败：' + str(e)[:140], 'name': name, 'turns': [], 'verdict': ''}
    turns = []
    for role, brief in ROLES:
        data = sl.get(role, {})
        msg = [{'role': 'system', 'content': SYS},
               {'role': 'user', 'content': '你是「' + role + '」分析师。' + brief + '。\n财报事实：'
                + json.dumps(data, ensure_ascii=False, default=str)[:4500]}]
        res = llm.chat(msg, temperature=0.35, max_tokens=max_tokens)
        turns.append({'role': role, 'status': 'ok' if res.get('ok') else 'error',
                      'text': res.get('text', ''), 'error': res.get('error')})
    ok = [t for t in turns if t['status'] == 'ok']
    verdict = ''
    if ok:
        summary = '\n'.join(['【' + t['role'] + '】' + (t.get('text') or '')[:420] for t in ok])[:4000]
        v = llm.chat([{'role': 'system', 'content': '你是财报圆桌主持人。综合各角色发言，给出 2-3 句明确裁决：关注 / 谨慎 / 规避 + 主要理由 + 1 个关键跟踪点。只依据发言内容，不编造。简体中文。'},
                      {'role': 'user', 'content': summary}], temperature=0.3, max_tokens=280)
        verdict = v.get('text', '') if v.get('ok') else ''
    return {'ok': True, 'code': code, 'name': name, 'turns': turns, 'verdict': verdict}
