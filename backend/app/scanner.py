# -*- coding: utf-8 -*-
"""扫描/分析编排：三表 -> 指标 -> 勾稽 -> 异常 -> 取证 -> 桥 -> 变点 -> 评分。"""
from concurrent.futures import ThreadPoolExecutor
from . import normalize, indicators, anomaly, checks as checks_mod, report as report_mod, store
from . import forensics, bridge as bridge_mod, crosscheck, changepoint, risk as risk_mod, struct as struct_mod, warehouse


def trim(canon, ind, periods=12):
    """裁剪返回体：只保留最近 N 个报告期（前端最多用 8 期），显著减小响应体积。"""
    out = dict(canon)
    for k in ('资产负债表', '利润表', '现金流量表'):
        out[k] = (canon.get(k) or [])[:periods]
    ind2 = dict(ind)
    ind2['rows'] = (ind.get('rows') or [])[:periods]
    return out, ind2


def analyze(code, ttl=6 * 3600, advanced=True, periods=12):
    canon = normalize.canonical(code, ttl)
    ind = indicators.compute(canon)
    cks = checks_mod.run(canon)
    anm = anomaly.run(canon, ind)
    rep = report_mod.build(canon, ind, cks, anm)
    out = {'canonical': canon, 'indicators': ind, 'checks': cks, 'anomalies': anm, 'report': rep}
    if advanced:
        try:
            fo = forensics.run(canon)
            br = bridge_mod.run(canon)
            cx = crosscheck.run(canon)
            cp = changepoint.run(ind)
            rk = risk_mod.run(canon, ind, cks, anm, fo, br, cp)
            try:
                stru = struct_mod.run(code)
            except Exception as e:
                stru = {'available': False, 'reason': str(e)[:120]}
            out.update({'forensics': fo, 'bridge': br, 'crosscheck': cx, 'changepoints': cp, 'risk': rk, 'structure': stru})
            rep['risk_score'] = {'score': rk['score'], 'level': rk['level']}
        except Exception as e:
            out['advanced_error'] = str(e)[:200]
    try:
        warehouse.save_statements(canon['code'], canon)
        warehouse.save_indicators(canon['code'], ind)
    except Exception:
        pass
    c2, i2 = trim(canon, ind, periods)
    out['canonical'] = c2
    out['indicators'] = i2
    return out


def _scan_one(w, ttl):
    code = w['code']
    try:
        r = analyze(code, ttl)
    except Exception as e:
        return {'code': code, 'error': str(e)[:200]}
    canon, anm, rep = r['canonical'], r['anomalies'], r['report']
    period = rep['period']
    prev = store.get_snapshot(code, period)
    if w['last_period'] != period:
        store.add_alert({'code': code, 'name': canon['name'], 'level': 'info', 'category': '新披露',
                         'title': '披露新报告期 ' + period, 'detail': rep['summary'], 'period': period})
    if prev is None:
        for a in anm:
            store.add_alert({'code': code, 'name': canon['name'], 'level': a['level'], 'category': a['category'],
                             'title': a['title'], 'detail': a['detail'], 'period': a['period']})
    else:
        old = set([x['title'] + '@' + x['period'] for x in prev.get('anomalies', [])])
        for a in anm:
            if (a['title'] + '@' + a['period']) not in old and a['level'] in ('high', 'medium'):
                store.add_alert({'code': code, 'name': canon['name'], 'level': a['level'], 'category': a['category'],
                                 'title': a['title'], 'detail': a['detail'], 'period': a['period']})
    rk = r.get('risk') or {}
    if rk.get('level') == '高' and (prev is None or (prev.get('risk') or {}).get('level') != '高'):
        store.add_alert({'code': code, 'name': canon['name'], 'level': 'high', 'category': '综合风险',
                         'title': '综合风险评分 ' + str(rk.get('score')) + '（高）',
                         'detail': '；'.join([d['name'] for d in (rk.get('drivers') or [])[:4]]), 'period': period})
    store.put_snapshot(code, period, {
        'name': canon['name'],
        'anomalies': [{'level': a['level'], 'category': a['category'], 'title': a['title'], 'period': a['period'], 'detail': a['detail']} for a in anm],
        'checks_summary': rep['checks_summary'],
        'risk': {'score': rk.get('score'), 'level': rk.get('level')},
    })
    store.mark_scanned(code, period)
    return {'code': code, 'name': canon['name'], 'period': period, 'anomalies': len(anm),
            'checks': rep['checks_summary'], 'risk': {'score': rk.get('score'), 'level': rk.get('level')}}


def scan_once(ttl=3 * 3600, workers=4):
    items = store.list_watch()
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
        return list(ex.map(lambda w: _scan_one(w, ttl), items))
