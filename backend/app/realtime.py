# -*- coding: utf-8 -*-
"""实时行情 / 指数 / 资金流（复用老系统 ai-invest-desk 的东财+腾讯端点）。"""
import time
import requests
from .datasource import cache_get, cache_put

UA = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
TX = 'https://qt.gtimg.cn/q='
EM_HOSTS = ['https://push2.eastmoney.com', 'https://82.push2.eastmoney.com', 'https://push2his.eastmoney.com']
INDICES = [('1.000001', '000001', '上证指数'), ('0.399001', '399001', '深证成指'),
           ('0.399006', '399006', '创业板指'), ('1.000300', '000300', '沪深300'),
           ('1.000688', '000688', '科创50')]


def _n(v, scale=1.0):
    try:
        if v in (None, '', '-'):
            return None
        return float(v) / scale if scale != 1.0 else float(v)
    except Exception:
        return None


def norm(code):
    s = str(code or '')
    import re
    m = re.search(r'(\d{6})', s)
    return m.group(1) if m else None


def secid(code):
    c = norm(code)
    return None if not c else (('1.' if c[0] == '6' else '0.') + c)


def txcode(code):
    c = norm(code)
    return None if not c else (('sh' if c[0] == '6' else 'sz') + c)


def _cached(key, ttl, fn):
    v = cache_get(key, ttl)
    if v is not None:
        return v
    try:
        v = fn()
    except Exception as e:
        return {'ok': False, 'error': str(e)[:160]}
    if v and v.get('ok'):
        cache_put(key, v)
    return v


def quote_tx(code):
    c = norm(code)
    if not c:
        return {'ok': False, 'error': '代码不合法'}
    r = requests.get(TX + txcode(c), timeout=8, headers=UA)
    r.encoding = 'gbk'
    m = r.text.split('"')
    if len(m) < 2:
        raise RuntimeError('腾讯无返回')
    t = m[1].split('~')
    if len(t) < 47 or not _n(t[3]):
        raise RuntimeError('腾讯数据不完整')
    return {'ok': True, 'source': 'tencent', 'code': t[2] or c, 'name': t[1] or '',
            'price': _n(t[3]), 'prevClose': _n(t[4]), 'open': _n(t[5]),
            'high': _n(t[33]), 'low': _n(t[34]), 'change': _n(t[31]), 'changePct': _n(t[32]),
            'volume': _n(t[6]), 'amount': (_n(t[37]) or 0) * 10000, 'turnoverPct': _n(t[38]),
            'pe': _n(t[39]), 'pb': _n(t[46]),
            'marketCap': (_n(t[45]) or 0) * 1e8, 'floatCap': (_n(t[44]) or 0) * 1e8,
            'ts': time.time()}


def quote_em(code):
    sid = secid(code)
    fields = 'f43,f44,f45,f46,f47,f48,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170'
    last = None
    for base in EM_HOSTS:
        try:
            j = requests.get(base + '/api/qt/stock/get', params={'secid': sid, 'fields': fields}, timeout=8, headers=UA).json()
            d = j.get('data') or {}
            if not d.get('f57'):
                continue
            return {'ok': True, 'source': 'eastmoney', 'code': str(d.get('f57')), 'name': d.get('f58') or '',
                    'price': (_n(d.get('f43')) or 0) / 100.0, 'prevClose': (_n(d.get('f60')) or 0) / 100.0,
                    'open': (_n(d.get('f46')) or 0) / 100.0, 'high': (_n(d.get('f44')) or 0) / 100.0,
                    'low': (_n(d.get('f45')) or 0) / 100.0, 'change': (_n(d.get('f169')) or 0) / 100.0,
                    'changePct': (_n(d.get('f170')) or 0) / 100.0, 'volume': _n(d.get('f47')),
                    'amount': _n(d.get('f48')), 'turnoverPct': (_n(d.get('f168')) or 0) / 100.0,
                    'pe': (_n(d.get('f162')) or 0) / 100.0, 'pb': (_n(d.get('f167')) or 0) / 100.0,
                    'marketCap': _n(d.get('f116')), 'floatCap': _n(d.get('f117')), 'ts': time.time()}
        except Exception as e:
            last = e
    raise last or RuntimeError('东财无返回')


def quote(code, ttl=30):
    c = norm(code)
    if not c:
        return {'ok': False, 'error': '代码不合法'}
    def f():
        try:
            return quote_tx(c)
        except Exception:
            return quote_em(c)
    return _cached('rt:q:' + c, ttl, f)


def market_fflow(ttl=900):
    """大盘资金流（上证指数主力净流入历史，用于总览图表）。"""
    def f():
        qs = {'secid': '1.000001', 'klt': 101, 'lmt': 20,
              'fields1': 'f1,f2,f3,f7', 'fields2': 'f51,f52,f53,f54,f55,f56'}
        last = None
        for base in EM_HOSTS[:2]:
            try:
                j = requests.get(base + '/api/qt/stock/fflow/kline/get', params=qs, timeout=8, headers=UA).json()
                klines = (j.get('data') or {}).get('klines') or []
                rows = []
                for line in klines:
                    p = str(line).split(',')
                    if len(p) >= 2:
                        rows.append({'date': p[0], 'main': _n(p[1])})
                if rows:
                    return {'ok': True, 'source': 'eastmoney', 'items': rows}
            except Exception as e:
                last = e
        return {'ok': False, 'error': (str(last)[:120] if last else 'no data')}
    return _cached('mktfflow', ttl, f)


TXK = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='


def index_sparks(ttl=900):
    """指数近 30 日收盘价（供前端迷你折线）。"""
    def f():
        out = []
        for secid, code, name in INDICES:
            tx = ('sh' if str(secid).startswith('1.') else 'sz') + code
            closes = []
            try:
                j = requests.get(TXK + tx + ',day,,,30,qfq', timeout=8, headers=UA).json()
                d = (j.get('data') or {}).get(tx) or {}
                rows = d.get('qfqday') or d.get('day') or []
                for x in rows:
                    try:
                        closes.append(round(float(x[2]), 2))
                    except Exception:
                        continue
            except Exception:
                pass
            out.append({'code': code, 'name': name, 'spark': closes[-30:]})
        return {'ok': True, 'indices': out}
    return _cached('idxspark', ttl, f)


def indices(ttl=30):
    def f():
        secids = ','.join([i[0] for i in INDICES])
        last = None
        for base in EM_HOSTS[:2]:
            try:
                j = requests.get(base + '/api/qt/ulist.np/get',
                                 params={'fltt': 2, 'secids': secids, 'fields': 'f2,f3,f12,f14'},
                                 timeout=8, headers=UA).json()
                diff = (j.get('data') or {}).get('diff') or {}
                rows = list(diff.values()) if isinstance(diff, dict) else list(diff)
                if not rows:
                    continue
                by = {str(d.get('f12')): d for d in rows}
                return {'ok': True, 'source': 'eastmoney', 'ts': time.time(),
                        'indices': [{'code': code, 'name': (by.get(code, {}) or {}).get('f14') or name,
                                     'price': _n((by.get(code, {}) or {}).get('f2')),
                                     'changePct': _n((by.get(code, {}) or {}).get('f3'))} for _s, code, name in INDICES]}
            except Exception as e:
                last = e
        # 腾讯兜底
        url = TX + ','.join(['sh000001', 'sz399001', 'sz399006', 'sh000300', 'sh000688'])
        r = requests.get(url, timeout=8, headers=UA)
        r.encoding = 'gbk'
        out = []
        for line in r.text.split('\n'):
            if '="' not in line:
                continue
            t = line.split('"')[1].split('~')
            if len(t) < 33:
                continue
            code = str(t[2]).zfill(6)
            meta = [x for x in INDICES if x[1] == code]
            out.append({'code': code, 'name': t[1] or (meta[0][2] if meta else ''), 'price': _n(t[3]), 'changePct': _n(t[32])})
        if not out:
            raise last or RuntimeError('指数无返回')
        return {'ok': True, 'source': 'tencent', 'ts': time.time(), 'indices': out}
    return _cached('rt:idx', ttl, f)


def fundflow(code, lmt=30, ttl=120):
    c = norm(code)
    if not c:
        return {'ok': False, 'error': '代码不合法'}
    def f():
        sid = secid(c)
        qs = {'secid': sid, 'klt': 101, 'lmt': max(1, min(int(lmt), 200)),
              'fields1': 'f1,f2,f3,f7', 'fields2': 'f51,f52,f53,f54,f55,f56'}
        last = None
        for base in EM_HOSTS[:2]:
            try:
                j = requests.get(base + '/api/qt/stock/fflow/kline/get', params=qs, timeout=8, headers=UA).json()
                d = j.get('data') or {}
                klines = d.get('klines') or []
                if not klines:
                    continue
                rows = []
                for line in klines:
                    p = str(line).split(',')
                    rows.append({'date': p[0], 'main': _n(p[1]), 'small': _n(p[2]),
                                 'medium': _n(p[3]), 'large': _n(p[4]), 'super': _n(p[5])})
                last_row = rows[-1]
                return {'ok': True, 'source': 'eastmoney', 'code': c, 'name': d.get('name') or '',
                        'date': last_row['date'], 'main': last_row['main'], 'super': last_row['super'],
                        'large': last_row['large'], 'medium': last_row['medium'], 'small': last_row['small'],
                        'history': [{'date': r['date'], 'main': r['main']} for r in rows], 'ts': time.time()}
            except Exception as e:
                last = e
        raise last or RuntimeError('资金流无返回')
    return _cached('rt:ff:' + c, ttl, f)
