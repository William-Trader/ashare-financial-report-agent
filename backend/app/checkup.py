# -*- coding: utf-8 -*-
"""财报体检（特化）：科目结构占比 + 同比变动 Top + 质量评分。"""
from .normalize import find_period

BS_BASE = '总资产'
IS_BASE = '营业总收入'


def _g(stmt, date):
    it = find_period(stmt, date)
    return it['values'] if it else {}


def _n(v):
    return v if isinstance(v, (int, float)) else None


def _prev_year(dates, d):
    y = str(int(d[:4]) - 1)
    t = y + d[4:]
    if t in dates:
        return t
    cand = [x for x in dates if x[:4] == y]
    return max(cand) if cand else None


def structure(canon, date, base_field, stmt, top=12):
    v = _g(stmt, date)
    base = _n(v.get(base_field))
    if not base:
        return []
    rows = []
    for k, val in v.items():
        if k == base_field or val is None:
            continue
        if abs(val) < 1e6:
            continue
        rows.append({'item': k, 'value': val, 'pct': round(val / base * 100, 2)})
    rows.sort(key=lambda x: -abs(x['pct']))
    return rows[:top]


def movers(canon, date, stmt, top=10):
    dates = sorted([it['date'] for it in stmt], reverse=True)
    p = _prev_year(dates, date)
    if not p:
        return []
    cur, prev = _g(stmt, date), _g(stmt, p)
    out = []
    for k, val in cur.items():
        if val is None:
            continue
        pv = _n(prev.get(k))
        if pv is None:
            continue
        d = val - pv
        out.append({'item': k, 'cur': val, 'prev': pv, 'delta': d,
                    'pct': (None if pv == 0 else round(d / abs(pv) * 100, 1))})
    out.sort(key=lambda x: -abs(x['delta']))
    return out[:top]


QUALITY_WEIGHTS = [('毛利率%', 0.15, True), ('归母净利率%', 0.15, True), ('ROE(归母权益)%', 0.2, True),
                   ('净现比', 0.2, True), ('收现比', 0.1, True), ('扣非占比%', 0.1, True),
                   ('资产负债率%', 0.1, False)]


def quality(ind):
    rows = ind.get('rows') or []
    if not rows:
        return None
    idx = rows[0]['indices']
    score = 0.0
    detail = []
    for k, w, higher in QUALITY_WEIGHTS:
        v = idx.get(k)
        if not isinstance(v, (int, float)):
            detail.append({'metric': k, 'value': None, 'score': None})
            continue
        if k == '净现比':
            s = max(0.0, min(1.0, v / 1.2))
        elif k == '收现比':
            s = max(0.0, min(1.0, v / 1.1))
        elif k == '扣非占比%':
            s = max(0.0, min(1.0, v / 100.0))
        elif k == 'ROE(归母权益)%':
            s = max(0.0, min(1.0, v / 20.0))
        elif k == '毛利率%':
            s = max(0.0, min(1.0, v / 50.0))
        elif k == '归母净利率%':
            s = max(0.0, min(1.0, v / 25.0))
        elif k == '资产负债率%':
            s = max(0.0, min(1.0, (100 - v) / 100.0))
        else:
            s = 0.5
        score += w * s
        detail.append({'metric': k, 'value': round(v, 2) if isinstance(v, (int, float)) else v, 'score': round(s, 2)})
    return {'score': round(score * 100, 1), 'grade': '优' if score >= 0.75 else ('良' if score >= 0.6 else ('中' if score >= 0.4 else '差')),
            'detail': detail}


def run(canon, ind, date=None):
    bs, is_, cf = canon['资产负债表'], canon['利润表'], canon['现金流量表']
    dates = sorted([it['date'] for it in is_], reverse=True)
    date = date or (dates[0] if dates else None)
    if not date:
        return {'ok': False, 'reason': '无报告期'}
    return {'ok': True, 'period': date, 'name': canon.get('name'), 'code': canon.get('code'),
            'quality': quality(ind),
            'bs_structure': structure(canon, date, BS_BASE, bs),
            'is_structure': structure(canon, date, IS_BASE, is_),
            'movers': movers(canon, date, is_) + movers(canon, date, bs),
            'note': '结构占比以总资产/营业总收入为基数；变动为同比（上年同期）'}
