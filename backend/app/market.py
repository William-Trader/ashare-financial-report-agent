# -*- coding: utf-8 -*-
"""全市场财报快照 + 异动监测（东财业绩报表 yjbb_em）。"""
import akshare as ak
from .datasource import cached, records
from . import warehouse


def _f(v):
    if v is None:
        return None
    s = str(v).replace(',', '').replace('%', '').strip()
    if s in ('', '--', '-', 'None', 'nan'):
        return None
    try:
        return float(s)
    except Exception:
        return None


def board_of(code):
    c = str(code).zfill(6)
    if c[:3] in ('688', '689'):
        return '科创板'
    if c[0] == '6':
        return '沪主板'
    if c[0] == '0':
        return '深主板'
    if c[0] == '3':
        return '创业板'
    if c[0] in ('4', '8', '9'):
        return '北交所'
    return '其他'


def a_codes(ttl=24 * 3600):
    """A 股白名单（排除新三板/退市），用于过滤全市场快照。"""
    def fetch():
        try:
            df = records(ak.stock_info_a_code_name())
        except Exception:
            return None
        out = {}
        for r in df:
            c = r.get('code') or r.get('代码')
            n = r.get('name') or r.get('名称')
            if c:
                out[str(c).strip().zfill(6)] = str(n or '')
        return out or None
    return cached('acodes:v1', ttl, fetch) or {}


def detect(row):
    """返回异动标签列表（按严重度排序）。"""
    tags = []
    np_yoy = row['np_yoy']
    np_qoq = row['np_qoq']
    rev_yoy = row['rev_yoy']
    np_ = row['np']
    if np_ is not None and np_ < 0:
        tags.append(('亏损', 'dn', 4))
    if np_yoy is not None:
        if np_yoy <= -50:
            tags.append(('净利暴雷 ' + fmt(np_yoy), 'dn', 4))
        elif np_yoy <= -20:
            tags.append(('净利下滑 ' + fmt(np_yoy), 'warn', 3))
        if np_yoy >= 100:
            tags.append(('净利爆发 ' + fmt(np_yoy), 'up', 4))
        elif np_yoy >= 30:
            tags.append(('净利高增 ' + fmt(np_yoy), 'up', 2))
    if np_qoq is not None and np_qoq <= -50:
        tags.append(('净利环比骤降 ' + fmt(np_qoq), 'dn', 3))
    if rev_yoy is not None and np_yoy is not None and rev_yoy > 10 and np_yoy < -20:
        tags.append(('增收不增利', 'warn', 4))
    tags.sort(key=lambda x: -x[2])
    return tags


def fmt(v):
    if v is None:
        return '—'
    return ('+' if v > 0 else '') + str(round(v, 1)) + '%'


def snapshot(date='', ttl=6 * 3600, force=False, limit=200, board=None, category=None):
    if force:
        ttl = 0
    if not date:
        date = latest_period(ttl)
    key = 'mkt2:' + date
    def fetch():
        try:
            return records(ak.stock_yjbb_em(date=date))
        except Exception:
            return None
    try:
        from . import safe
        df = safe.with_timeout(lambda: cached(key, ttl, fetch), 8, None, 'snapshot:' + str(date))
    except Exception:
        df = cached(key, ttl, fetch)
    if not df:
        for fallback in [d for d in CANDIDATES if d != date]:
            df = cached('mkt2:' + fallback, ttl, fetch_fb(fallback))
            if df:
                date = fallback
                break
    if not df:
        return {'available': False, 'date': date, 'reason': '业绩报表接口不可用'}
    white = a_codes()
    rows = []
    seen = set()
    for r in df:
        code = str(r.get('股票代码', '')).zfill(6)
        if code in seen or (white and code not in white):
            continue
        seen.add(code)
        row = {
            'code': code,
            'name': str(r.get('股票简称', '')),
            'eps': _f(r.get('每股收益')),
            'rev': _f(r.get('营业总收入-营业总收入')),
            'rev_yoy': _f(r.get('营业总收入-同比增长')),
            'rev_qoq': _f(r.get('营业总收入-季度环比增长')),
            'np': _f(r.get('净利润-净利润')),
            'np_yoy': _f(r.get('净利润-同比增长')),
            'np_qoq': _f(r.get('净利润-季度环比增长')),
            'roe': _f(r.get('净资产收益率')),
            'gm': _f(r.get('销售毛利率')),
            'board': board_of(code),
        }
        row['tags'] = detect(row)
        rows.append(row)

    def n_in(cat):
        return sum(1 for r in rows if any(t[0].startswith(cat) for t in r['tags']))

    stats = {
        'total': len(rows),
        '亏损': n_in('亏损'),
        '暴雷': n_in('净利暴雷'),
        '爆发': n_in('净利爆发') + n_in('净利高增'),
        '异动': sum(1 for r in rows if r['tags']),
    }
    # 异动榜：按严重度 + |净利同比| 排序
    def sev(r):
        return max((t[2] for t in r['tags']), default=0)
    ranked = [r for r in rows if r['tags']]
    ranked.sort(key=lambda r: (-sev(r), -(abs(r['np_yoy']) if r['np_yoy'] is not None else 0)))
    # 板块统计
    boards = {}
    for r in rows:
        b = r['board']
        d = boards.setdefault(b, {'total': 0, '异动': 0, '暴雷': 0})
        d['total'] += 1
        if r['tags']:
            d['异动'] += 1
        if any(t[0].startswith('净利暴雷') or t[0] == '亏损' for t in r['tags']):
            d['暴雷'] += 1
    if board:
        ranked = [r for r in ranked if r['board'] == board]
    if category:
        ranked = [r for r in ranked if any(t[0].startswith(category) for t in r['tags'])]
    items = [{'code': r['code'], 'name': r['name'], 'np_yoy': r['np_yoy'], 'rev_yoy': r['rev_yoy'],
              'roe': r['roe'], 'gm': r['gm'], 'tags': r['tags'], 'board': r['board']} for r in ranked[:max(1, min(limit, 500))]]
    import time as _t
    try:
        if force or warehouse.market_snap_count(date) < len(rows):
            warehouse.save_market_snapshot(date, rows)
            warehouse.upsert_stocks([(r['code'], r['name'], r['board']) for r in rows[:6000]])
    except Exception:
        pass
    return {'available': True, 'date': date, 'as_of': _t.time(), 'stats': stats,
            'board': [{'board': k, **v, 'ratio': round(v['异动'] / v['total'] * 100, 1)} for k, v in boards.items()],
            'returned': len(items),
            'anomalies': items}


def digest(date='20260630', ttl=6 * 3600):
    snap = snapshot(date, ttl, limit=15)
    if not snap.get('available'):
        return snap
    st = snap['stats']
    boards = sorted(snap['board'], key=lambda b: -b['ratio'])
    lines = [
        '报告期 ' + snap['date'] + '：全市场披露 ' + str(st['total']) + ' 家，异动 ' + str(st['异动']) + ' 家。',
        '净利暴雷 ' + str(st['暴雷']) + ' 家，净利爆发 ' + str(st['爆发']) + ' 家，亏损 ' + str(st['亏损']) + ' 家。',
        '板块异动占比最高：' + '、'.join([b['board'] + ' ' + str(b['ratio']) + '%' for b in boards[:3]]) + '。',
        '重点异动（前 5）：' + '；'.join([r['name'] + '(' + r['code'] + ') ' + '、'.join([t[0] for t in r['tags']]) for r in snap['anomalies'][:5]]),
    ]
    return {'date': snap['date'], 'stats': st, 'board': snap['board'], 'top': snap['anomalies'][:15],
            'text': '\n'.join(lines)}


def boards_list(date='20260630', ttl=6 * 3600):
    return snapshot(date, ttl, limit=1).get('board', [])


def _all_rows_for(date, ttl):
    def fetch():
        try:
            df = records(ak.stock_yjbb_em(date=date))
        except Exception:
            return None
        white = a_codes()
        out = []
        seen = set()
        for r in df:
            code = str(r.get('股票代码', '')).zfill(6)
            if code in seen or (white and code not in white):
                continue
            seen.add(code)
            out.append({'code': code, 'name': str(r.get('股票简称', '')),
                        'np_yoy': _f(r.get('净利润-同比增长')), 'rev_yoy': _f(r.get('营业总收入-同比增长')),
                        'roe': _f(r.get('净资产收益率')), 'board': board_of(code)})
        return out
    try:
        from . import safe
        return safe.with_timeout(lambda: cached('mktall2:' + date, ttl, fetch), 8, None, 'all_rows:' + str(date))
    except Exception:
        return cached('mktall2:' + date, ttl, fetch)


CANDIDATES = ['20260930', '20260630', '20260331', '20251231', '20250930']


def latest_period(ttl=6 * 3600):
    """按新到旧探测有数据的报告期（修复数据滞后）。"""
    for d in CANDIDATES:
        if _all_rows_for(d, ttl):
            return d
    return CANDIDATES[0]


def all_rows(date='20260630', ttl=6 * 3600, force=False):
    rows = _all_rows_for(date, 0 if force else ttl)
    used = date
    if not rows:
        for fb in ('20260331', '20251231', '20250930'):
            rows = _all_rows_for(fb, ttl)
            if rows:
                used = fb
                break
    return {'date': used, 'rows': rows or []}


def search(q, date='20260630', limit=20, ttl=6 * 3600):
    q = (q or '').strip()
    if not q:
        return {'items': []}
    data = all_rows(date, ttl)
    out = []
    for r in data['rows']:
        if q in r['code'] or q in r['name']:
            out.append(r)
            if len(out) >= limit:
                break
    return {'date': data['date'], 'query': q, 'items': out}


def fetch_fb(date):
    def _f():
        try:
            return records(ak.stock_yjbb_em(date=date))
        except Exception:
            return None
    return _f
