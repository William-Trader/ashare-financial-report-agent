# -*- coding: utf-8 -*-
"""可执行建议：基于风险评分 + 指标 + 异常的规则引擎（可叠加 LLM）。"""
from . import llm


def rule_based(r):
    rk = r.get('risk') or {}
    anm = r.get('anomalies') or []
    rows = (r.get('indicators') or {}).get('rows') or []
    idx = rows[0]['indices'] if rows else {}
    score = rk.get('score', 0)

    signals = []
    if score >= 60:
        action, action_en, tone = '规避', 'Avoid', 'up'      # 红 = 危险
    elif score >= 30:
        action, action_en, tone = '谨慎', 'Caution', 'warn'  # 琥珀
    else:
        action, action_en, tone = '关注', 'Watch', 'dn'      # 绿 = 安全

    reasons = []
    for d in (rk.get('drivers') or [])[:4]:
        reasons.append(d['name'] + '：' + d['detail'])
    positives = []
    if isinstance(idx.get('净现比'), (int, float)):
        positives.append('净现比 %.2f' % idx['净现比'])
    if isinstance(idx.get('单季归母净利同比%'), (int, float)):
        positives.append('单季归母净利同比 %+.1f%%' % idx['单季归母净利同比%'])
    if isinstance(idx.get('毛利率%'), (int, float)):
        positives.append('毛利率 %.1f%%' % idx['毛利率%'])

    next_steps = ['核对最近一期报告附注的会计政策/估计变更', '核对非经常性损益明细与扣非口径']
    if action == '规避':
        next_steps += ['若已持仓，复核止损纪律与仓位', '等待扣非盈利与经营现金流同步改善']
    elif action == '谨慎':
        next_steps += ['缩小仓位或观察下一报告期确认', '跟踪应收账款周转与存货去化']
    else:
        next_steps += ['可纳入观察池，等待放量或业绩兑现', '对比同行业相对估值分位']

    # 核心判断：趋势 + 现金流质量 + 方向，一句话说清
    g = idx.get('单季归母净利同比%')
    ncr = idx.get('净现比')
    roe = idx.get('ROE(归母权益)%')
    trend = ('单季归母净利同比 %+.1f%%' % g) if isinstance(g, (int, float)) else '盈利趋势待确认'
    cashq = ('净现比 %.2f' % ncr) if isinstance(ncr, (int, float)) else '现金流质量待确认'
    profitq = ('ROE %.1f%%' % roe) if isinstance(roe, (int, float)) else ''
    core = '%s，%s%s；综合风险「%s」(%d/100)。' % (trend, cashq, ('，' + profitq) if profitq else '', rk.get('level', '中'), score)

    risks = [a['title'] for a in anm[:3]]
    conclusion_text = ('【结论】%s（风险分 %d/100）\n' % (action, score) +
                       '· 核心：%s\n' % core +
                       '· 依据：%s\n' % ('；'.join(reasons[:3]) or '未见显著驱动') +
                       '· 风险：%s\n' % ('；'.join(risks) or '未见显著异常') +
                       '· 操作：%s' % '；'.join(next_steps[:3]))

    return {'action': action, 'action_en': action_en, 'tone': tone, 'score': score,
            'reasons': reasons, 'positives': positives, 'next_steps': next_steps,
            'core': core, 'risks': risks, 'conclusion_text': conclusion_text,
            'conclusion': {'verdict': action, 'score': score, 'level': rk.get('level', '中'),
                           '核心判断': core, '关键依据': reasons, '主要风险': risks, '操作建议': next_steps}}


def build(r, with_llm=True):
    base = rule_based(r)
    base['code'] = r['report']['code']
    base['name'] = r['report']['name']
    base['period'] = r['report']['period']
    if with_llm:
        try:
            txt = llm.suggest(r)
            if txt.get('ok'):
                base['narrative'] = txt['text']
        except Exception:
            pass
    return base
