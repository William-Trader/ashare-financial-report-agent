# -*- coding: utf-8 -*-
"""组合收益归因：个股贡献 / 板块贡献（Brinson 简化版）。"""
from . import marketdata as md
from .datasource import to_em_symbol
from .realtime import norm


def run(codes, weights=None, days=60):
    codes = [c for c in (codes or []) if c][:20]
    if not codes:
        return {'ok': False, 'error': '需要 codes'}
    k = len(codes)
    w = list(weights[:k]) if weights and len(weights) >= k else [1.0 / k] * k
    s = sum(w) or 1.0
    w = [x / s for x in w]
    rows = []
    for i, c in enumerate(codes):
        daily = md.daily(c, max(30, days + 5))
        if len(daily) < 5:
            rows.append({'code': to_em_symbol(c), 'weight': round(w[i], 4), 'ret': None, 'contrib': None, 'board': None})
            continue
        seg = daily[-(days + 1):]
        ret = (seg[-1]['close'] / seg[0]['close'] - 1) * 100
        rows.append({'code': to_em_symbol(c), 'weight': round(w[i], 4), 'ret': round(ret, 2),
                     'contrib': round(w[i] * ret, 3), 'board': None})
    # 板块归属：用仓库 stocks 表
    try:
        from . import warehouse
        with warehouse.cursor() as cc:
            for r in rows:
                row = cc.execute('SELECT board FROM stocks WHERE code=?', (r['code'],)).fetchone()
                if row:
                    r['board'] = row[0]
    except Exception:
        pass
    total = sum(r['contrib'] or 0 for r in rows)
    boards = {}
    for r in rows:
        b = r['board'] or '未分类'
        d = boards.setdefault(b, {'weight': 0.0, 'contrib': 0.0, 'n': 0})
        d['weight'] += r['weight']
        d['contrib'] += (r['contrib'] or 0)
        d['n'] += 1
    for b, d in boards.items():
        d['weight'] = round(d['weight'], 4)
        d['contrib'] = round(d['contrib'], 3)
        d['contrib_pct'] = round(d['contrib'] / total * 100, 1) if total else None
    rows.sort(key=lambda x: -(x['contrib'] or 0))
    return {'ok': True, 'days': days, 'portfolio_return': round(total, 2),
            'items': rows, 'boards': boards, 'note': '区间收益 = 期末收盘/期初收盘-1；贡献 = 权重×收益；板块按仓库 stocks.board'}
