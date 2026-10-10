# -*- coding: utf-8 -*-
"""主营构成漂移与集中度（HHI），基于东财主营构成数据。"""
from .datasource import mainbiz, to_em_symbol


def _f(v):
    try:
        return float(str(v).replace(',', '').replace('%', ''))
    except Exception:
        return None


def run(code, top=8):
    rows = mainbiz(code)
    if not rows:
        return {'available': False, 'reason': '无主营构成数据'}
    kinds = {}
    for r in rows:
        k = str(r.get('分类类型') or '')
        kinds.setdefault(k, []).append(r)
    pick = None
    for k in kinds:
        if '产品' in k:
            pick = k
            break
    if pick is None:
        pick = next(iter(kinds))
    items = kinds[pick]
    dates = sorted(set(str(r.get('报告日期'))[:10] for r in items), reverse=True)
    if not dates:
        return {'available': False, 'reason': '无报告期'}
    latest = dates[0]
    cur = [r for r in items if str(r.get('报告日期'))[:10] == latest]
    cur = sorted(cur, key=lambda r: -(_f(r.get('收入比例')) or 0))[:top]
    shares = [(_f(r.get('收入比例')) or 0) / 100.0 for r in cur]
    hhi = round(sum(s * s for s in shares), 4)
    prev = None
    if len(dates) > 1:
        prev = dates[1]
        pcur = {str(r.get('主营构成')): _f(r.get('收入比例')) for r in items if str(r.get('报告日期'))[:10] == prev}
        prev = {'period': prev, 'shares': pcur}
    return {
        'available': True, 'basis': pick, 'period': latest,
        'top': [{'name': str(r.get('主营构成')), 'revenue': _f(r.get('主营收入')), 'share_pct': _f(r.get('收入比例')), 'cost_pct': _f(r.get('成本比例'))} for r in cur],
        'hhi': hhi, 'concentration': '高' if hhi > 0.3 else ('中' if hhi > 0.15 else '低'),
        'prev': prev,
    }
