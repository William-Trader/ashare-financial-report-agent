# -*- coding: utf-8 -*-
"""综合风险评分 + 证据回源 + 反事实核查清单。"""


def run(canon, ind, checks, anomalies, forensics, bridge, cps):
    drivers = []
    def add(weight, name, detail, evidence, hit):
        if hit:
            drivers.append({'weight': weight, 'name': name, 'detail': detail, 'evidence': evidence})

    bn = forensics.get('beneish')
    if bn and bn.get('flag'):
        add(20, 'Beneish M-Score 触发', 'M=' + str(bn['score']) + ' > -1.78，存在盈余操纵特征',
            ['Beneish@' + bn['period']], True)
    pf = forensics.get('piotroski')
    if pf and pf['score'] <= 3:
        add(12, 'Piotroski F-Score 偏低', 'F=' + str(pf['score']) + '/9，基本面动能弱', ['F-Score@' + pf['period']], True)
    az = forensics.get('altman')
    if az and az['zone'] == '危险':
        add(15, 'Altman Z″ 落入危险区', 'Z″=' + str(az['score']), ['Z-Score@' + az['period']], True)
    elif az and az['zone'] == '灰色':
        add(6, 'Altman Z″ 灰色区', 'Z″=' + str(az['score']), ['Z-Score@' + az['period']], True)
    for a in (forensics.get('accruals') or [])[:2]:
        if a.get('level') == '高':
            add(10, '应计比率偏高', '应计比率=' + str(a['accrual_ratio']), ['Sloan@' + a['period']], True)
    recent = sorted(set(a['period'] for a in anomalies), reverse=True)[:3]
    best = {}
    for a in anomalies:
        if a['period'] not in recent or a['level'] not in ('high', 'medium'):
            continue
        w = 9 if a['level'] == 'high' else 5
        if a['category'] not in best or w > best[a['category']][0]:
            best[a['category']] = (w, a)
    for _cat, (w, a) in best.items():
        add(w, a['category'], a['title'] + '（' + a['period'] + '）', a.get('evidence', []), True)
    for c in cps[:2]:
        if c.get('significant'):
            add(6, '指标结构性拐点', c['metric'] + ' 在 ' + c['break_period'] + ' 前后由 ' + str(c['before']) + ' 变为 ' + str(c['after']),
                [c['metric'] + '@' + c['break_period']], True)
    for b in bridge[:1]:
        if b.get('residual_ratio') is not None and b['residual_ratio'] > 40:
            add(8, '现金流桥残差较大', '未解释部分占经营现金流 ' + str(b['residual_ratio']) + '%',
                ['Bridge@' + b['period']], True)
    cs = {'pass': 0, 'warn': 0, 'fail': 0}
    for c in checks:
        if c['status'] in cs:
            cs[c['status']] += 1
    if cs['fail']:
        add(min(20, cs['fail'] * 3), '勾稽校验未通过', str(cs['fail']) + ' 项失败 / ' + str(cs['warn']) + ' 项预警',
            ['勾稽校验'], True)

    score = min(100, sum(d['weight'] for d in drivers))
    level = '高' if score >= 60 else ('中' if score >= 30 else '低')
    checklist = [
        '查会计报表附注「会计政策与会计估计变更」是否解释毛利率/费用率的结构性变化',
        '核对现金流量表补充资料中折旧摊销与营运资本变动，验证现金流桥残差',
        '核对应收账款账龄与前五大客户集中度，验证回款风险',
        '核对非经常性损益明细，判断扣非后盈利可持续性',
        '核对存货跌价准备与商誉减值测试，验证资产质量',
    ]
    return {'score': score, 'level': level, 'drivers': sorted(drivers, key=lambda x: -x['weight']),
            'checks_summary': cs, 'falsify_checklist': checklist}
