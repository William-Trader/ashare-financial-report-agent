# -*- coding: utf-8 -*-
"""自选股与告警存储（SQLite）。"""
import os, json, time, sqlite3
from contextlib import contextmanager

DATA_DIR = os.environ.get('FR_DATA_DIR', '/home/ubuntu/fr-agent/data')
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, 'fr.sqlite3')


@contextmanager
def cursor():
    """真正的连接上下文：提交后关闭，避免连接泄漏导致 database is locked。"""
    c = conn()
    try:
        yield c
        c.commit()
    finally:
        c.close()

def conn():
    c = sqlite3.connect(DB, timeout=30)
    c.execute('CREATE TABLE IF NOT EXISTS watchlist (code TEXT PRIMARY KEY, name TEXT, added_at REAL, last_period TEXT, last_scan REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, name TEXT, level TEXT, category TEXT, title TEXT, detail TEXT, period TEXT, created_at REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS snapshots (code TEXT, period TEXT, payload TEXT, created_at REAL, PRIMARY KEY (code, period))')
    c.execute('''CREATE TABLE IF NOT EXISTS positions (
        code TEXT PRIMARY KEY, name TEXT, cost REAL, qty REAL, stop REAL, target REAL, updated_at REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS track (
        id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, name TEXT, date TEXT, direction TEXT,
        confidence REAL, text TEXT, settled INTEGER DEFAULT 0, ret REAL, hit INTEGER, settle_date TEXT, created_at REAL)''')
    return c


def pos_upsert(code, name='', cost=None, qty=None, stop=None, target=None):
    import time as _t
    with cursor() as c:
        c.execute('INSERT INTO positions (code, name, cost, qty, stop, target, updated_at) VALUES (?,?,?,?,?,?,?) '
                  'ON CONFLICT(code) DO UPDATE SET name=COALESCE(excluded.name,name), cost=excluded.cost, qty=excluded.qty, '
                  'stop=excluded.stop, target=excluded.target, updated_at=excluded.updated_at',
                  (code, name, cost, qty, stop, target, _t.time()))
    return pos_list()


def pos_list():
    with cursor() as c:
        rows = c.execute('SELECT code, name, cost, qty, stop, target FROM positions ORDER BY updated_at DESC').fetchall()
    return [{'code': r[0], 'name': r[1], 'cost': r[2], 'qty': r[3], 'stop': r[4], 'target': r[5]} for r in rows]


def pos_del(code):
    with cursor() as c:
        c.execute('DELETE FROM positions WHERE code=?', (code,))
    return pos_list()


def track_add(code, name, direction, confidence, text=''):
    import time as _t
    d = _t.strftime('%Y-%m-%d')
    with cursor() as c:
        cur = c.execute('INSERT INTO track (code, name, date, direction, confidence, text, created_at) VALUES (?,?,?,?,?,?,?)',
                        (code, name, d, direction, float(confidence or 0.5), text, _t.time()))
        return {'id': cur.lastrowid, 'code': code, 'date': d, 'direction': direction}


def track_open():
    with cursor() as c:
        rows = c.execute('SELECT id, code, name, date, direction, confidence, text FROM track WHERE settled=0').fetchall()
    return [{'id': r[0], 'code': r[1], 'name': r[2], 'date': r[3], 'direction': r[4], 'confidence': r[5], 'text': r[6]} for r in rows]


def track_settle(tid, ret, hit, settle_date):
    with cursor() as c:
        c.execute('UPDATE track SET settled=1, ret=?, hit=?, settle_date=? WHERE id=?', (ret, hit, settle_date, tid))


def track_all(limit=300):
    with cursor() as c:
        rows = c.execute('SELECT id, code, name, date, direction, confidence, text, settled, ret, hit, settle_date FROM track ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return [{'id': r[0], 'code': r[1], 'name': r[2], 'date': r[3], 'direction': r[4], 'confidence': r[5],
             'text': r[6], 'settled': r[7], 'ret': r[8], 'hit': r[9], 'settle_date': r[10]} for r in rows]


def add_watch(code, name=''):
    with cursor() as c:
        c.execute('INSERT OR IGNORE INTO watchlist (code, name, added_at) VALUES (?,?,?)', (code, name, time.time()))
        c.execute('UPDATE watchlist SET name=? WHERE code=? AND (name IS NULL OR name=?)', (name, code, ''))
    return list_watch()


def remove_watch(code):
    with cursor() as c:
        c.execute('DELETE FROM watchlist WHERE code=?', (code,))
    return list_watch()


def list_watch():
    with cursor() as c:
        rows = c.execute('SELECT code, name, added_at, last_period, last_scan FROM watchlist ORDER BY added_at').fetchall()
    return [{'code': r[0], 'name': r[1], 'added_at': r[2], 'last_period': r[3], 'last_scan': r[4]} for r in rows]


def mark_scanned(code, period):
    with cursor() as c:
        c.execute('UPDATE watchlist SET last_period=?, last_scan=? WHERE code=?', (period, time.time(), code))


def add_alert(a):
    with cursor() as c:
        c.execute('INSERT INTO alerts (code, name, level, category, title, detail, period, created_at) VALUES (?,?,?,?,?,?,?,?)',
                  (a.get('code'), a.get('name'), a.get('level'), a.get('category'), a.get('title'), a.get('detail'), a.get('period'), time.time()))


def list_alerts(limit=100):
    with cursor() as c:
        rows = c.execute('SELECT code, name, level, category, title, detail, period, created_at FROM alerts ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return [{'code': r[0], 'name': r[1], 'level': r[2], 'category': r[3], 'title': r[4], 'detail': r[5], 'period': r[6], 'created_at': r[7]} for r in rows]


def clear_alerts():
    with cursor() as c:
        c.execute('DELETE FROM alerts')


def get_snapshot(code, period):
    with cursor() as c:
        r = c.execute('SELECT payload FROM snapshots WHERE code=? AND period=?', (code, period)).fetchone()
    return json.loads(r[0]) if r else None


def put_snapshot(code, period, payload):
    with cursor() as c:
        c.execute('INSERT OR REPLACE INTO snapshots (code, period, payload, created_at) VALUES (?,?,?,?)',
                  (code, period, json.dumps(payload, ensure_ascii=False), time.time()))
