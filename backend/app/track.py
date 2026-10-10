# -*- coding: utf-8 -*-
"""结论校准闭环（复刻老系统 track.js）：登记结论 -> 到期用真实行情结算 -> 命中率 / Brier。"""
import time
from . import marketdata as md
from .datasource import to_em_symbol

HORIZON = 5  # 5 个交易日


def _entry_price(code, after_date=None):
    k = md.daily(code, 400)
    if not k:
        return None, None
    if after_date:
        for i, x in enumerate(k):
            if x['date'] >= after_date:
                return x['date'], x['close']
        return None, None
    return k[-1]['date'], k[-1]['close']


def register(code, direction, confidence, text='', name=''):
    from .store import track_add
    return track_add(to_em_symbol(code), name, direction, confidence, text)


def settle():
    from .store import track_open, track_settle
    n = 0
    for row in track_open():
        code, base_date = row['code'], row['date']
        k = md.daily(code, 400)
        if not k:
            continue
        idx = None
        for i, x in enumerate(k):
            if x['date'] >= base_date:
                idx = i
                break
        if idx is None or idx + HORIZON >= len(k):
            continue
        ret = (k[idx + HORIZON]['close'] / k[idx]['close'] - 1) * 100
        d = row['direction']
        hit = 1 if (d == '多' and ret > 0) or (d == '空' and ret < 0) or (d == '中性' and abs(ret) < 1.5) else 0
        track_settle(row['id'], round(ret, 3), hit, k[idx + HORIZON]['date'])
        n += 1
    return n


def stats():
    from .store import track_all
    rows = [r for r in track_all() if r['settled']]
    if not rows:
        return {'n': 0, 'hit_rate': None, 'brier': None, 'by_direction': {}}
    hits = sum(1 for r in rows if r['hit'])
    brier = sum((r['confidence'] - r['hit']) ** 2 for r in rows) / len(rows)
    by = {}
    for r in rows:
        d = by.setdefault(r['direction'], {'n': 0, 'hit': 0})
        d['n'] += 1; d['hit'] += r['hit']
    for d in by.values():
        d['hit_rate'] = round(d['hit'] / d['n'] * 100, 1)
    return {'n': len(rows), 'hit_rate': round(hits / len(rows) * 100, 1),
            'brier': round(brier, 4), 'by_direction': by, 'horizon_days': HORIZON,
            'note': '多:5日收益>0 空:<0 中性:|收益|<1.5%；confidence 为登记时置信度'}
