# -*- coding: utf-8 -*-
"""事件驱动：龙虎榜 / 融资融券 / 大宗交易 / 公告 / 业绩预告（复用老系统 events.js 的东财端点）。"""
import time
import requests
from .datasource import cache_get, cache_put

DC = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
ANN = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
HDR = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'}


def _n(v):
    try:
        return float(v)
    except Exception:
        return None


def _dc(report, filt='', extra='', ttl=900, label=''):
    url = DC + '?reportName=' + report + '&columns=ALL&pageSize=30' + (('&filter=' + requests.utils.quote(filt)) if filt else '') + extra
    def f():
        r = requests.get(url, timeout=12, headers=HDR)
        j = r.json()
        rows = ((j.get('result') or {}).get('data')) or []
        return {'ok': True, 'rows': rows}
    v = cache_get('ev:' + label + ':' + filt, ttl)
    if v is not None:
        return v
    try:
        v = f()
    except Exception as e:
        return {'ok': False, 'rows': [], 'error': str(e)[:140]}
    if v.get('ok'):
        cache_put('ev:' + label + ':' + filt, v)
    return v


def billboard(code):
    v = _dc('RPT_DAILYBILLBOARD_DETAILSNEW', '(\u0053\u0045\u0043\u0055\u0052\u0049\u0054\u0059\u005F\u0043\u004F\u0044\u0045="' + code + '")', '&sortColumns=TRADE_DATE&sortTypes=-1', label='bb')
    out = []
    for r in v['rows'][:15]:
        out.append({'date': str(r.get('TRADE_DATE') or '')[:10], 'reason': r.get('EXPLANATION') or r.get('EXPLAIN') or '',
                    'net': _n(r.get('BILLBOARD_NET_AMT')), 'buy': _n(r.get('BILLBOARD_BUY_AMT')),
                    'sell': _n(r.get('BILLBOARD_SELL_AMT'))})
    return {'ok': v['ok'], 'items': out, 'error': v.get('error')}


def rzrq(code):
    v = _dc('RPTA_WEB_RZRQ_GGMX', '(\u0053\u0043\u004F\u0044\u0045="' + code + '")', '&sortColumns=DATE&sortTypes=-1', label='rz')
    if not v['ok'] or not v['rows']:
        v = _dc('RPTA_WEB_RZRQ_GGMX', '(\u0053\u0045\u0043\u0055\u0052\u0049\u0054\u0059\u005F\u0043\u004F\u0044\u0045="' + code + '")', '&sortColumns=DATE&sortTypes=-1', label='rz2')
    out = []
    for r in v['rows'][:15]:
        out.append({'date': str(r.get('DATE') or '')[:10], 'rzye': _n(r.get('RZYE')), 'rzmre': _n(r.get('RZMRE')),
                    'rzche': _n(r.get('RZCHE')), 'rqye': _n(r.get('RQYE'))})
    return {'ok': v['ok'], 'items': out, 'error': v.get('error')}


def blocktrade(code):
    v = _dc('RPT_DATA_BLOCKTRADE', '(\u0053\u0045\u0043\u0055\u0052\u0049\u0054\u0059\u005F\u0043\u004F\u0044\u0045="' + code + '")', '&sortColumns=TRADE_DATE&sortTypes=-1', label='bt')
    out = []
    for r in v['rows'][:15]:
        out.append({'date': str(r.get('TRADE_DATE') or '')[:10], 'price': _n(r.get('DEAL_PRICE')),
                    'volume': _n(r.get('DEAL_VOLUME')), 'amount': _n(r.get('DEAL_AMT')),
                    'premium': _n(r.get('PREMIUM_RATIO')), 'buyer': r.get('BUYER_NAME') or ''})
    return {'ok': v['ok'], 'items': out, 'error': v.get('error')}


def announcements(code):
    url = ANN + '?page_size=30&page_index=1&ann_type=A&client_source=web&stock_list=' + code
    def f():
        r = requests.get(url, timeout=12, headers={'User-Agent': HDR['User-Agent'], 'Referer': 'https://data.eastmoney.com/'})
        j = r.json()
        return ((j.get('data') or {}).get('list')) or []
    v = cache_get('ev:ann:' + code, 900)
    if v is None:
        try:
            v = {'ok': True, 'items': f()}
        except Exception as e:
            v = {'ok': False, 'items': [], 'error': str(e)[:140]}
        if v.get('ok'):
            cache_put('ev:ann:' + code, v)
    out = []
    for r in (v.get('items') or [])[:15]:
        out.append({'date': str(r.get('notice_date') or r.get('eiTime') or '')[:10], 'title': r.get('title') or '',
                    'type': (r.get('columns') or [{}])[0].get('column_name') if r.get('columns') else ''})
    return {'ok': v.get('ok'), 'items': out, 'error': v.get('error')}


def forecast(code):
    v = _dc('RPT_PUBLIC_OP_NEWPREDICT', '(\u0053\u0045\u0043\u0055\u0052\u0049\u0054\u0059\u005F\u0043\u004F\u0044\u0045="' + code + '")', '&sortColumns=NOTICE_DATE&sortTypes=-1', label='fc')
    out = []
    for r in v['rows'][:10]:
        out.append({'date': str(r.get('NOTICE_DATE') or '')[:10], 'period': str(r.get('REPORT_DATE') or '')[:10],
                    'type': r.get('PREDICT_TYPE') or '', 'change': _n(r.get('PREDICT_FINANCE')),
                    'reason': (r.get('CHANGE_REASON_EXPLAIN') or '')[:120]})
    return {'ok': v['ok'], 'items': out, 'error': v.get('error')}


def all_events(code, days=60):
    from . import warehouse
    src = {'龙虎榜': billboard(code), '融资融券': rzrq(code), '大宗交易': blocktrade(code),
           '公告': announcements(code), '业绩预告': forecast(code)}
    items = []
    for name, d in src.items():
        for it in d.get('items', []):
            it = dict(it)
            it['source'] = name
            items.append(it)
    items.sort(key=lambda x: x.get('date') or '', reverse=True)
    try:
        warehouse.save_events(code, items[:60])
    except Exception:
        pass
    return {'code': code, 'as_of': time.time(), 'items': items[:60],
            'sources': {k: {'ok': v.get('ok'), 'count': len(v.get('items', [])), 'error': v.get('error')} for k, v in src.items()}}
