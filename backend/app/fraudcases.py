# -*- coding: utf-8 -*-
"""造假案例验证：用红旗引擎 + 风险分评估已知财务造假/暴雷公司。

目的：把「功能清单」变成「被验证的能力」——若引擎能在这些高危标的上密集报警，
说明它识别的正是真正重要的信号。
"""
from . import scanner, deep

CASES = [
    {'code': '600518', 'name': '康美药业', 'incident': '2018 年财务造假（虚增货币资金 299 亿）'},
    {'code': '002450', 'name': '康得新', 'incident': '2019 年造假（虚增利润 119 亿、存贷双高）'},
    {'code': '002069', 'name': '獐子岛', 'incident': '2014-2018 存货（扇贝）异常'},
    {'code': '300104', 'name': '乐视网', 'incident': '2016-2017 资金链断裂 / 关联交易'},
    {'code': '600781', 'name': '辅仁药业', 'incident': '2019 分红违约 / 大股东资金占用'},
    {'code': '300072', 'name': '三聚环保', 'incident': '2019 应收账款与现金流质疑'},
    {'code': '002766', 'name': '索菱股份', 'incident': '2019 财务造假（虚增营收利润）'},
    {'code': '000408', 'name': '藏格控股', 'incident': '2019 关联方资金占用 / 违规担保'},
]


def run_cases():
    out = []
    for c in CASES:
        rec = {'code': c['code'], 'name': c['name'], 'incident': c['incident']}
        try:
            r = scanner.analyze(c['code'], 6 * 3600, advanced=True, periods=8)
            rep = r.get('report') or {}
            rk = r.get('risk') or {}
            d = deep.run(r['canonical'], r['indicators'])
            rf = [f.get('name') for f in (d.get('redflags') or [])]
            anm = [a.get('title') for a in (r.get('anomalies') or [])]
            rec['period'] = rep.get('period')
            rec['risk_score'] = rk.get('score')
            rec['risk_level'] = rk.get('level')
            rec['redflags'] = rf
            rec['anomalies'] = anm[:6]
            rec['flags_n'] = len(rf) + len(anm)
        except Exception as e:
            rec['error'] = str(e)[:120]
            rec['flags_n'] = 0
        out.append(rec)
    out.sort(key=lambda x: -x.get('flags_n', 0))
    tot = sum(1 for x in out if x.get('flags_n', 0) >= 3 or (x.get('risk_level') == '高'))
    return {'ok': True, 'cases': out, 'hit_cases': tot, 'total': len(out),
            'note': '用现有红旗规则 + 异常识别 + 风险分评估已知造假/暴雷公司；命中（红旗/异常≥3 或 风险等级=高）越多，说明引擎越能识别真正的高危标的。'}
