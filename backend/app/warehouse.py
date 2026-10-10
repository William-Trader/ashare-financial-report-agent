# -*- coding: utf-8 -*-
"""本地数据仓库：股票 / 三表 / 指标 / K线 / 全市场快照 / 事件，落盘可累积。"""
import os, json, time, sqlite3
from contextlib import contextmanager

DATA_DIR = os.environ.get('FR_DATA_DIR', '/home/ubuntu/fr-agent/data')
DB = os.path.join(DATA_DIR, 'warehouse.sqlite3')

DDL = [
    'CREATE TABLE IF NOT EXISTS stocks (code TEXT PRIMARY KEY, name TEXT, board TEXT, industry TEXT, updated_at REAL)',
    'CREATE TABLE IF NOT EXISTS statements (code TEXT, period TEXT, kind TEXT, payload TEXT, updated_at REAL, PRIMARY KEY (code, period, kind))',
    'CREATE TABLE IF NOT EXISTS indicators (code TEXT, period TEXT, payload TEXT, updated_at REAL, PRIMARY KEY (code, period))',
    'CREATE TABLE IF NOT EXISTS kline (code TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL, volume REAL, PRIMARY KEY (code, date))',
    'CREATE TABLE IF NOT EXISTS market_snap (snap_date TEXT, code TEXT, name TEXT, board TEXT, np_yoy REAL, rev_yoy REAL, roe REAL, gm REAL, np REAL, rev REAL, tag TEXT, PRIMARY KEY (snap_date, code))',
    'CREATE TABLE IF NOT EXISTS events (code TEXT, event_date TEXT, source TEXT, title TEXT, payload TEXT, created_at REAL)',
    'CREATE INDEX IF NOT EXISTS ix_snap_date ON market_snap (snap_date)',
    'CREATE INDEX IF NOT EXISTS ix_kline_code ON kline (code)',
    'CREATE INDEX IF NOT EXISTS ix_ev_code ON events (code)',
    'CREATE TABLE IF NOT EXISTS research (code TEXT PRIMARY KEY, name TEXT, period TEXT, risk_score REAL, risk_level TEXT, verdict TEXT, tone TEXT, track TEXT, track_name TEXT, key_json TEXT, anomalies_json TEXT, checks_json TEXT, updated_at REAL)',
    'CREATE INDEX IF NOT EXISTS ix_res_risk ON research (risk_score)',
]


@contextmanager
def cursor():
    """真正的连接上下文：提交后关闭，避免连接泄漏导致 database is locked。"""
    c = conn()
    try:
        yield c
        c.commit()
    finally:
        c.close()

_SCHEMA_READY = False


def conn():
    global _SCHEMA_READY
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    if not _SCHEMA_READY:
        c.execute('PRAGMA journal_mode=WAL')  # 持久化到 DB 文件，只需设一次
        for d in DDL:
            c.execute(d)
        _SCHEMA_READY = True
    c.execute('PRAGMA synchronous=NORMAL')  # WAL 下推荐，降低写事务 fsync 延迟
    return c


def _j(v):
    return json.dumps(v, ensure_ascii=False, default=str)


def upsert_stock(code, name=None, board=None, industry=None):
    with cursor() as c:
        c.execute('INSERT INTO stocks (code, name, board, industry, updated_at) VALUES (?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET name=COALESCE(excluded.name,name), board=COALESCE(excluded.board,board), industry=COALESCE(excluded.industry,industry), updated_at=excluded.updated_at',
                  (code, name, board, industry, time.time()))


def upsert_stocks(items):
    rows = [(it[0], it[1], it[2], None, time.time()) for it in items]
    with cursor() as c:
        c.executemany('INSERT INTO stocks (code, name, board, industry, updated_at) VALUES (?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET name=COALESCE(excluded.name,name), board=COALESCE(excluded.board,board), industry=COALESCE(excluded.industry,industry), updated_at=excluded.updated_at', rows)
    return len(rows)


def market_snap_count(date):
    with cursor() as c:
        return c.execute('SELECT COUNT(*) FROM market_snap WHERE snap_date=?', (date,)).fetchone()[0]


def save_statements(code, canon):
    rows = 0
    with cursor() as c:
        for kind in ('资产负债表', '利润表', '现金流量表'):
            for it in canon.get(kind) or []:
                c.execute('INSERT OR REPLACE INTO statements (code, period, kind, payload, updated_at) VALUES (?,?,?,?,?)',
                          (code, it.get('date'), kind, _j(it), time.time()))
                rows += 1
    # 注意：upsert_stock 会另开连接，必须在上面的事务提交之后调用，否则自锁 (database is locked)
    name = canon.get('name')
    if name:
        upsert_stock(code, name)
    return rows


def save_indicators(code, ind):
    rows = 0
    with cursor() as c:
        for r in ind.get('rows') or []:
            c.execute('INSERT OR REPLACE INTO indicators (code, period, payload, updated_at) VALUES (?,?,?,?)',
                      (code, r.get('date'), _j(r), time.time()))
            rows += 1
    return rows


def save_kline(code, rows):
    n = 0
    with cursor() as c:
        for r in rows or []:
            c.execute('INSERT OR REPLACE INTO kline (code, date, open, close, high, low, volume) VALUES (?,?,?,?,?,?,?)',
                      (code, r.get('date'), r.get('open'), r.get('close'), r.get('high'), r.get('low'), r.get('volume')))
            n += 1
    return n


def save_market_snapshot(date, rows):
    n = 0
    with cursor() as c:
        for r in rows or []:
            c.execute('INSERT OR REPLACE INTO market_snap (snap_date, code, name, board, np_yoy, rev_yoy, roe, gm, np, rev, tag) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                      (date, r.get('code'), r.get('name'), r.get('board'), r.get('np_yoy'), r.get('rev_yoy'),
                       r.get('roe'), r.get('gm'), r.get('np'), r.get('rev'),
                       '|'.join([t[0] for t in (r.get('tags') or [])])))
            n += 1
    return n


def save_events(code, items):
    n = 0
    with cursor() as c:
        for it in items or []:
            c.execute('INSERT INTO events (code, event_date, source, title, payload, created_at) VALUES (?,?,?,?,?,?)',
                      (code, it.get('date'), it.get('source'), it.get('title') or it.get('reason') or '', _j(it), time.time()))
            n += 1
    return n


def stats():
    out = {'db': DB, 'size_kb': None}
    try:
        out['size_kb'] = round(os.path.getsize(DB) / 1024, 1)
    except Exception:
        pass
    with cursor() as c:
        for t in ('stocks', 'statements', 'indicators', 'kline', 'market_snap', 'events'):
            try:
                out[t] = c.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]
            except Exception:
                out[t] = None
        out['snap_dates'] = [r[0] for r in c.execute('SELECT DISTINCT snap_date FROM market_snap ORDER BY snap_date DESC LIMIT 12').fetchall()]
        out['stocks_with_statements'] = c.execute('SELECT COUNT(DISTINCT code) FROM statements').fetchone()[0]
        out['stocks_with_kline'] = c.execute('SELECT COUNT(DISTINCT code) FROM kline').fetchone()[0]
        out['latest_period'] = c.execute('SELECT MAX(period) FROM indicators').fetchone()[0]
    return out


def market_snap(date=None):
    with cursor() as c:
        if not date:
            date = c.execute('SELECT MAX(snap_date) FROM market_snap').fetchone()[0]
        rows = c.execute('SELECT code, name, board, np_yoy, rev_yoy, roe, gm, np, rev, tag FROM market_snap WHERE snap_date=?', (date,)).fetchall()
    return date, [{'code': r[0], 'name': r[1], 'board': r[2], 'np_yoy': r[3], 'rev_yoy': r[4],
                   'roe': r[5], 'gm': r[6], 'np': r[7], 'rev': r[8], 'tag': r[9]} for r in rows]


def kline(code):
    with cursor() as c:
        rows = c.execute('SELECT date, open, close, high, low, volume FROM kline WHERE code=? ORDER BY date', (code,)).fetchall()
    return [{'date': r[0], 'open': r[1], 'close': r[2], 'high': r[3], 'low': r[4], 'volume': r[5]} for r in rows]
