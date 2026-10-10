# -*- coding: utf-8 -*-
"""数据源层：基于 akshare 抓取 A 股三大报表 / 财务摘要 / 指标，带 SQLite 缓存。"""
import os, json, time, sqlite3
import pandas as pd
import akshare as ak

DATA_DIR = os.environ.get('FR_DATA_DIR', '/home/ubuntu/fr-agent/data')
CACHE_DIR = os.path.join(DATA_DIR, 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_DB = os.path.join(CACHE_DIR, 'cache.sqlite3')
DEFAULT_TTL = 6 * 3600


def _conn():
    c = sqlite3.connect(CACHE_DB, timeout=30)
    c.execute('CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, ts REAL, v TEXT)')
    c.execute('CREATE INDEX IF NOT EXISTS ix_kv_ts ON kv (ts)')
    return c


_CAP_CTR = [0]
CACHE_MAX_ROWS = 12000
CACHE_TRIM_TO = 10000


def cache_get(key, ttl):
    try:
        with _conn() as c:
            row = c.execute('SELECT ts, v FROM kv WHERE k=?', (key,)).fetchone()
        if row and (ttl <= 0 or time.time() - row[0] < ttl):
            return json.loads(row[1])
    except Exception:
        pass
    return None


def cache_put(key, value):
    try:
        with _conn() as c:
            c.execute('INSERT OR REPLACE INTO kv (k, ts, v) VALUES (?,?,?)',
                      (key, time.time(), json.dumps(value, ensure_ascii=False)))
            _CAP_CTR[0] += 1
            if _CAP_CTR[0] % 400 == 0:
                n = c.execute('SELECT COUNT(*) FROM kv').fetchone()[0]
                if n > CACHE_MAX_ROWS:
                    c.execute('DELETE FROM kv WHERE k IN (SELECT k FROM kv ORDER BY ts ASC LIMIT ?)', (n - CACHE_TRIM_TO,))
    except Exception:
        pass


def cached(key, ttl, fn):
    v = cache_get(key, ttl)
    if v is not None:
        return v
    v = fn()
    if v is not None:
        cache_put(key, v)
    return v


def retry(fn, tries=3, delay=0.8, backoff=2.0):
    """对易抖动的行情接口做重试；全部失败时抛出最后一次异常。"""
    last = None
    for i in range(max(1, tries)):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(delay * (backoff ** i))
    raise last


def cache_stats():
    try:
        with _conn() as c:
            n = c.execute('SELECT COUNT(*) FROM kv').fetchone()[0]
            newest = c.execute('SELECT MAX(ts) FROM kv').fetchone()[0]
        return {'entries': n, 'newest_ts': newest}
    except Exception:
        return {'entries': 0, 'newest_ts': None}


def to_em_symbol(code):
    code = str(code).strip().upper()
    if code[:2] in ('SH', 'SZ', 'BJ'):
        return code
    code = code.zfill(6)
    if code[0] == '6':
        return 'SH' + code
    if code[0] in ('0', '3'):
        return 'SZ' + code
    if code[0] in ('4', '8', '9'):
        return 'BJ' + code
    return 'SH' + code


def records(df):
    df = df.copy()
    df.columns = [str(c) for c in df.columns]
    return json.loads(df.to_json(orient='records', force_ascii=False, date_format='iso'))


def balance_sheet(code, ttl=DEFAULT_TTL):
    sym = to_em_symbol(code)
    return cached('bs:' + sym, ttl,
                  lambda: retry(lambda: records(ak.stock_balance_sheet_by_report_em(symbol=sym))))


def profit_sheet(code, ttl=DEFAULT_TTL):
    sym = to_em_symbol(code)
    return cached('is:' + sym, ttl,
                  lambda: retry(lambda: records(ak.stock_profit_sheet_by_report_em(symbol=sym))))


def cash_flow(code, ttl=DEFAULT_TTL):
    sym = to_em_symbol(code)
    return cached('cf:' + sym, ttl,
                  lambda: retry(lambda: records(ak.stock_cash_flow_sheet_by_report_em(symbol=sym))))


def financial_abstract(code, ttl=DEFAULT_TTL):
    sym = to_em_symbol(code)
    code6 = sym[2:]
    return cached('abs:' + sym, ttl,
                  lambda: retry(lambda: records(ak.stock_financial_abstract(symbol=code6))))


def fin_indicators(code, start_year=None, ttl=DEFAULT_TTL):
    sym = to_em_symbol(code)
    code6 = sym[2:]
    if start_year is None:
        start_year = str(time.localtime().tm_year - 6)
    key = 'ind:' + sym + ':' + start_year
    return cached(key, ttl,
                  lambda: retry(lambda: records(ak.stock_financial_analysis_indicator(symbol=code6, start_year=start_year))))


def stock_name(code):
    sym = to_em_symbol(code)
    def _f():
        try:
            bs = ak.stock_balance_sheet_by_report_em(symbol=sym)
            if len(bs):
                return str(bs.iloc[0].get('SECURITY_NAME_ABBR', ''))
        except Exception:
            pass
        return ''
    return cached('name:' + sym, 24 * 3600, _f)


def mainbiz(code, ttl=24 * 3600):
    sym = to_em_symbol(code)
    return cached('mb:' + sym, ttl, lambda: retry(lambda: records(ak.stock_zygc_em(symbol=sym)), tries=2))


def bundle(code, ttl=DEFAULT_TTL):
    """一次性取回三大报表 + 摘要 + 指标。"""
    return {
        'code': to_em_symbol(code),
        'name': stock_name(code),
        'balance': balance_sheet(code, ttl),
        'profit': profit_sheet(code, ttl),
        'cashflow': cash_flow(code, ttl),
        'abstract': financial_abstract(code, ttl),
        'indicators': fin_indicators(code, ttl=ttl),
    }
