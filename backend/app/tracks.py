# -*- coding: utf-8 -*-
"""财报赛道分类 + 财报对比（机构级）。前端「财报赛道 / 财报对比」页的数据源。"""
from . import warehouse, scanner, realtime as rt


TRACKS = [
    {'key': 'hyper', 'name': '爆发增长', 'desc': '营收高增 + 净利爆发，成长动能最强', 'color': '#e5483f',
     'rule': lambda r: (r['np_yoy'] is not None and r['np_yoy'] >= 50 and r['rev_yoy'] is not None and r['rev_yoy'] >= 30)},
    {'key': 'growth', 'name': '稳健成长', 'desc': '营收与净利双位数增长', 'color': '#df8a3f',
     'rule': lambda r: (r['np_yoy'] is not None and r['np_yoy'] >= 20 and r['rev_yoy'] is not None and r['rev_yoy'] >= 15)},
    {'key': 'quality', 'name': '质量白马', 'desc': '高 ROE + 盈利稳定，增长平缓', 'color': '#c9a45c',
     'rule': lambda r: (r['roe'] is not None and r['roe'] >= 20 and (r['np'] or 0) > 0 and (r['rev_yoy'] is None or r['rev_yoy'] < 20))},
    {'key': 'cashcow', 'name': '现金奶牛', 'desc': '高毛利 + 正 ROE，成熟现金牛', 'color': '#2ba471',
     'rule': lambda r: (r['gm'] is not None and r['gm'] >= 40 and r['roe'] is not None and 0 < r['roe'] < 20 and (r['np_yoy'] is None or r['np_yoy'] < 50))},
    {'key': 'turnaround', 'name': '困境反转', 'desc': '低基数净利大增，或由亏转盈', 'color': '#4f8de3',
     'rule': lambda r: ((r['np_yoy'] is not None and r['np_yoy'] >= 100 and (r['np'] or 0) > 0) or ('爆发' in (r['tag'] or '')))},
    {'key': 'risk', 'name': '风险规避', 'desc': '亏损 / 净利暴雷，需规避', 'color': '#b03a3a',
     'rule': lambda r: ('亏损' in (r['tag'] or '') or '暴雷' in (r['tag'] or ''))},
]
OTHER = {'key': 'other', 'name': '均衡其他', 'desc': '未落入上述赛道的标的', 'color': '#8a8f98',
         'rule': lambda r: True}


def run(date=None):
    d, rows = warehouse.market_snap(date)
    if not rows:
        return {'ok': False, 'reason': '仓库暂无快照，请先在「数据仓库」执行同步', 'date': d}
    buckets = {t['key']: [] for t in TRACKS}
    buckets['other'] = []
    for r in rows:
        hit = False
        for t in TRACKS:
            if t['rule'](r):
                buckets[t['key']].append(r)
                hit = True
                break
        if not hit:
            buckets['other'].append(r)

    def _top(items, n=30):
        items = sorted(items, key=lambda x: (x['np_yoy'] is None, -(x['np_yoy'] or 0)))
        return [{'code': x['code'], 'name': x['name'], 'board': x['board'], 'np_yoy': x['np_yoy'],
                 'rev_yoy': x['rev_yoy'], 'roe': x['roe'], 'gm': x['gm']} for x in items[:n]]

    out = []
    for t in TRACKS + [OTHER]:
        items = buckets.get(t['key'], [])
        out.append({'key': t['key'], 'name': t['name'], 'desc': t['desc'], 'color': t['color'],
                    'count': len(items), 'top': _top(items)})
    total = len(rows)
    return {'ok': True, 'date': d, 'total': total,
            'tracks': out,
            'summary': [{'key': t['key'], 'name': t['name'], 'count': len(buckets.get(t['key'], [])),
                         'pct': round(100.0 * len(buckets.get(t['key'], [])) / total, 1) if total else 0}
                        for t in TRACKS + [OTHER]]}


def compare(codes, date=None):
    """2+ 只标的财报对比：核心指标 + 同比 + 风险 + 估值 并排。"""
    codes = [str(c).strip().zfill(6) for c in (codes or []) if str(c).strip()]
    codes = list(dict.fromkeys(codes))[:6]
    if len(codes) < 2:
        return {'ok': False, 'reason': '至少选 2 只标的'}
    cols = []
    for code in codes:
        col = {'code': code}
        try:
            r = scanner.analyze(code, 6 * 3600, advanced=True, periods=6)
        except Exception as e:
            col['error'] = str(e)[:120]
            cols.append(col)
            continue
        rep = r.get('report') or {}
        inc = (r.get('indicators') or {}).get('rows') or []
        idx = inc[0]['indices'] if inc and inc[0].get('indices') else {}
        rk = r.get('risk') or {}
        q = rt.quote(code)
        col['name'] = rep.get('name') or idx.get('name')
        col['period'] = rep.get('period')
        col['指标'] = {k: idx.get(k) for k in
                       ['单季营业总收入(元)', '单季归母净利润(元)', '单季营收同比%', '单季归母净利同比%', '毛利率%', '归母净利率%',
                        'ROE(归母权益)%', '资产负债率%', '净现比', '收现比', '扣非占比%', '单季经营现金流同比%']}
        col['风险'] = {'score': rk.get('score'), 'level': rk.get('level')}
        col['勾稽'] = rep.get('checks_summary')
        col['估值'] = {'pe': q.get('pe'), 'pb': q.get('pb'), '市值': q.get('marketCap'),
                       '涨跌%': q.get('changePct'), '价': q.get('price')} if q.get('ok') else {}
        cols.append(col)
    return {'ok': True, 'codes': codes, 'cols': cols}
