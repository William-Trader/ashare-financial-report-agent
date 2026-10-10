# -*- coding: utf-8 -*-
"""行情历史（腾讯）+ 公司档案/行业（东财 F10）。"""
import time
import requests
from .datasource import cache_get, cache_put, to_em_symbol, retry
from .realtime import norm, txcode

UA = {'User-Agent': 'Mozilla/5.0'}
TXK = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='
F10 = 'https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code='


def _cache(key, ttl, fn):
    v = cache_get(key, ttl)
    if v is not None:
        return v
    try:
        v = fn()
    except Exception:
        return None
    if v:
        cache_put(key, v)
    return v


def daily(code, n=250, ttl=1800):
    """前复权日线（腾讯）。返回 [{date, open, close, high, low, volume}] 时间正序。"""
    tx = txcode(code)
    if not tx:
        return []
    def f():
        r = requests.get(TXK + tx + ',day,,,' + str(max(20, min(int(n), 800))) + ',qfq', timeout=15, headers=UA)
        j = r.json()
        node = (j.get('data') or {}).get(tx) or {}
        rows = node.get('qfqday') or node.get('day') or []
        out = []
        for x in rows:
            try:
                out.append({'date': x[0], 'open': float(x[1]), 'close': float(x[2]),
                            'high': float(x[3]), 'low': float(x[4]), 'volume': float(x[5])})
            except Exception:
                continue
        if out:
            try:
                from . import warehouse
                warehouse.save_kline(tx[2:], out)
            except Exception:
                pass
        return out or None
    return _cache('k:' + tx + ':' + str(n), ttl, f) or []


def profile(code):
    """公司档案：行业三级分类 + 证监会行业 + 基本信息（东财 F10）。"""
    em = to_em_symbol(code)
    def f():
        r = requests.get(F10 + em, timeout=15,
                         headers={'User-Agent': UA['User-Agent'], 'Referer': 'https://emweb.securities.eastmoney.com/'})
        j = r.json()
        jb = (j.get('jbzl') or [{}])
        jb = jb[0] if jb else {}
        return {'ok': True, 'code': em, 'org': jb.get('ORG_NAME') or '', 'name': jb.get('SECURITY_NAME_ABBR') or '',
                'industry': jb.get('EM2016') or '', 'industry_csrc': jb.get('INDUSTRYCSRC1') or '',
                'type': jb.get('SECURITY_TYPE') or '', 'chairman': jb.get('CHAIRMAN') or '',
                'secretary': jb.get('SECRETARY') or '', 'list_market': jb.get('TRADE_MARKET') or '',
                'founded': str(jb.get('FOUND_DATE') or '')[:10], 'list_date': str(jb.get('LISTING_DATE') or '')[:10]}
    v = _cache('f10:' + em, 24 * 3600, f)
    return v or {'ok': False, 'reason': '公司档案不可用'}
