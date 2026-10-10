# -*- coding: utf-8 -*-
"""研报纠错核查（竞赛选题5）：把草稿里的数字/口径/期间与系统事实逐条比对，给出问题与建议。"""
import re, json
from . import scanner, llm

SYS = ('你是投研报告审校员。给你【系统事实】与【报告草稿】，逐条核验草稿中的数字与说法。'
       '只依据系统事实判断，禁止自行发明数字。输出严格 JSON：'
       '{"issues":[{"级别":"高/中/低","类型":"数值不符/口径错误/期间错误/来源缺失/逻辑矛盾","草稿原文":"",'
       '"系统事实":"","建议":"","依据":""}],"summary":"一句话总体判断","score":0-100}'
       '。没有问题时 issues 为空。')


def facts(code):
    r = scanner.analyze(code, 6 * 3600, advanced=True, periods=8)
    rep, rows, anm = r['report'], (r['indicators']['rows'] or []), (r.get('anomalies') or [])
    inc = rows[0]['indices'] if rows else {}
    keep = ['毛利率%', '归母净利率%', 'ROE(归母权益)%', '资产负债率%', '净现比', '收现比', '扣非占比%',
            '单季营收同比%', '单季归母净利同比%', '单季经营现金流同比%']
    return {'code': rep.get('code'), 'name': rep.get('name'), 'period': rep.get('period'),
            '指标': {k: inc.get(k) for k in keep},
            '勾稽': rep.get('checks_summary'),
            '异常': [{'类别': a['category'], '期间': a['period'], '说明': a['title']} for a in anm[:6]],
            '风险': {'分数': (r.get('risk') or {}).get('score'), '等级': (r.get('risk') or {}).get('level')}}


def run(code, draft, use_llm=True):
    f = facts(code)
    # 规则层：从草稿抓数字，与事实池做粗略一致性检查（先给可解释的确定性结果）
    nums = re.findall(r'(\d+(?:\.\d+)?)\s*(%|亿元|亿|万元|万)', draft or '')
    pool = {k: v for k, v in (f.get('指标') or {}).items() if isinstance(v, (int, float))}
    rule_hits = []
    for val, unit in nums[:40]:
        v = float(val)
        if unit == '%':
            near = [(k, x) for k, x in pool.items() if abs(x - v) < 0.05]
            if near:
                continue
            # 草稿百分比在系统里找不到近似值 → 待核
            rule_hits.append({'unit': '%', 'value': v})
    issues = []
    if '免责' not in (draft or '') and '不构成投资建议' not in (draft or ''):
        issues.append({'级别': '低', '类型': '来源缺失', '草稿原文': '（未见免责声明）',
                       '系统事实': '—', '建议': '补充「数据来源 + 不构成投资建议」免责声明', '依据': '合规要求'})
    if use_llm:
        msg = [{'role': 'system', 'content': SYS},
               {'role': 'user', 'content': '【系统事实】' + json.dumps(f, ensure_ascii=False, default=str)[:4000] +
                '\n\n【报告草稿】\n' + (draft or '')[:4000]}]
        res = llm.chat(msg, temperature=0.1, max_tokens=1200, timeout=150, deep=False)
        txt = (res.get('text') or '').strip()
        i, j = txt.find('{'), txt.rfind('}')
        llm_out = None
        try:
            llm_out = json.loads(txt[i:j + 1]) if i >= 0 and j > i else None
        except Exception:
            llm_out = None
    else:
        llm_out = None
    if llm_out and isinstance(llm_out.get('issues'), list):
        for x in llm_out['issues']:
            issues.append({'级别': x.get('级别', '中'), '类型': x.get('类型', ''), '草稿原文': str(x.get('草稿原文', ''))[:120],
                           '系统事实': str(x.get('系统事实', ''))[:120], '建议': str(x.get('建议', ''))[:160],
                           '依据': str(x.get('依据', ''))[:120]})
    return {'ok': True, 'code': f.get('code'), 'name': f.get('name'), 'period': f.get('period'),
            'facts': f, 'issues': issues,
            'llm_summary': (llm_out or {}).get('summary'), 'llm_score': (llm_out or {}).get('score'),
            'rule_stats': {'numbers_in_draft': len(nums), 'unmatched_pct': len(rule_hits)},
            'note': '规则层给确定性结果，LLM 层做语义核验；两者都只依据系统事实，请人工复核后采信'}
