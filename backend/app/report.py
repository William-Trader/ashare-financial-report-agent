# -*- coding: utf-8 -*-
"""报告层：结构化数据 + 指标表 + 归因 + 证据链 + 风险清单 + 整体结论。"""
from .normalize import find_period


def _fmt(v):
    if v is None or not isinstance(v, (int, float)):
        return 'N/A'
    a = abs(v)
    if a >= 1e8:
        return str(round(v / 1e8, 2)) + '亿元'
    if a >= 1e4:
        return str(round(v / 1e4, 2)) + '万元'
    return str(round(v, 2))


def _pctf(v):
    return 'N/A' if v is None or not isinstance(v, (int, float)) else str(round(v, 2)) + '%'


def build(canon, ind, checks, anomalies):
    rows = ind.get('rows', [])
    if not rows:
        return {'summary': '无可用数据', 'attribution': [], 'evidence': [], 'risks': [], 'checks_summary': {}, 'conclusion': ''}
    latest = rows[0]
    idx = latest['indices']
    d = latest['date']

    summary_lines = [
        canon['name'] + '(' + canon['code'] + ') 最新报告期 ' + d + '（' + str(latest.get('report_name') or latest.get('type')) + '）',
        '营业总收入 ' + _fmt(_num(canon['利润表'], d, '营业总收入')) + '，归母净利润 ' + _fmt(_num(canon['利润表'], d, '归母净利润')),
        '毛利率 ' + _pctf(idx.get('毛利率%')) + '，归母净利率 ' + _pctf(idx.get('归母净利率%')) + '，ROE ' + _pctf(idx.get('ROE(归母权益)%')),
        '资产负债率 ' + _pctf(idx.get('资产负债率%')) + '，净现比 ' + (str(round(idx['净现比'], 2)) if isinstance(idx.get('净现比'), (int, float)) else 'N/A'),
    ]

    attribution = []
    labels = [('单季营收同比%', '营业总收入'), ('单季归母净利同比%', '归母净利润'),
              ('单季扣非同比%', '扣非归母净利润'), ('单季经营现金流同比%', '经营活动现金流净额')]
    for key, name in labels:
        v = idx.get(key)
        if isinstance(v, (int, float)):
            direction = '增长' if v >= 0 else '下滑'
            attribution.append({'item': name, 'yoy_pct': round(v, 2),
                                'text': name + direction + ' ' + str(round(abs(v), 1)) + '%（单季同比）'})
    mg = idx.get('毛利率%')
    if isinstance(mg, (int, float)):
        attribution.append({'item': '毛利率', 'value': round(mg, 2),
                            'text': '毛利率 ' + str(round(mg, 1)) + '%，费用率（销售/管理/研发）合计 ' + _pctf(_sum3(idx))})

    evidence = []
    for it in canon['利润表'][:1] + canon['资产负债表'][:1] + canon['现金流量表'][:1]:
        evidence.append({'statement': it.get('name') or it['date'], 'period': it['date'], 'fields': list(it['values'].keys())})
    for a in anomalies:
        evidence.append({'statement': a['category'], 'period': a['period'], 'fields': a.get('evidence', [])})

    by_level = {'high': [], 'medium': [], 'low': []}
    for a in anomalies:
        by_level.setdefault(a['level'], []).append(a)
    risks = []
    for lvl, tag in (('high', '高'), ('medium', '中'), ('low', '低')):
        for a in by_level.get(lvl, []):
            risks.append({'level': tag, 'category': a['category'], 'title': a['title'], 'period': a['period']})

    cs = {'pass': 0, 'warn': 0, 'fail': 0, 'skip': 0}
    for c in checks:
        cs[c['status']] = cs.get(c['status'], 0) + 1

    conclusion = ('勾稽校验：通过 ' + str(cs['pass']) + ' 项，预警 ' + str(cs['warn']) +
                  ' 项，失败 ' + str(cs['fail']) + ' 项。' +
                  ('存在高风险信号 ' + str(len(by_level['high'])) + ' 条，建议重点核查。' if by_level['high']
                   else ('存在中风险信号 ' + str(len(by_level['medium'])) + ' 条，需持续跟踪。' if by_level['medium']
                         else '未发现显著异常信号。')))

    return {
        'code': canon['code'], 'name': canon['name'], 'period': d,
        'summary': '\n'.join(summary_lines),
        'attribution': attribution,
        'evidence': evidence,
        'risks': risks,
        'checks_summary': cs,
        'conclusion': conclusion,
    }


def _num(stmt, date, field):
    it = find_period(stmt, date)
    if not it:
        return None
    v = it['values'].get(field)
    return v if isinstance(v, (int, float)) else None


def _sum3(idx):
    vals = [idx.get('销售费用率%'), idx.get('管理费用率%'), idx.get('研发费用率%')]
    vals = [v for v in vals if isinstance(v, (int, float))]
    return sum(vals) if vals else None
