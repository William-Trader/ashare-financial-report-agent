# -*- coding: utf-8 -*-
"""公告结构化提取：拉公告正文 -> 分类 -> LLM 抽取关键字段（质押/中标/股权变动/减值/诉讼/担保…）。
对应竞赛选题「数据结构化提取」：从非标准化公告中提取关键字段并结构化输出。"""
import json
from . import llm
from .datasource import cache_get, cache_put

UA = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'}
LIST_API = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
CONTENT_API = 'https://np-cnotice-stock.eastmoney.com/api/content/ann'
DETAIL = 'https://data.eastmoney.com/notices/detail/'

CATS = {
    '股份质押': ['质押'],
    '中标/订单': ['中标', '中选', '框架协议'],
    '股权变动': ['权益变动', '股权转让', '协议转让', '要约收购'],
    '资产减值': ['减值', '计提'],
    '诉讼仲裁': ['诉讼', '仲裁'],
    '对外担保': ['担保'],
    '股份回购': ['回购'],
    '股东增减持': ['减持', '增持'],
    '关联交易': ['关联交易'],
    '业绩预告/快报': ['业绩预告', '业绩快报', '预增', '预减'],
    '分红送转': ['利润分配', '分红', '转增'],
    '监管/问询': ['问询', '监管', '处罚'],
    '会计政策/估计变更': ['会计政策', '会计估计', '政策变更', '追溯调整', '重述'],
    '审计/内控': ['审计', '内控', '非标'],
}

EXTRACT_SYS = ('你是 A 股公告结构化抽取器。只依据给定的公告正文抽取字段，禁止猜测；正文没有就写 null。'
               '输出严格 JSON（不要多余文字），字段：'
               '{"类型": "", "涉及主体": "", "金额_元": null, "比例_百分比": null, "期限": "", '
               '"关键条款": "", "对财报影响": "利好/利空/中性/不明确", "影响程度": "高/中/低", "原文证据": "（不超过 40 字的原文片段）"}')


def _list(code, n=30, ttl=1800):
    key = 'ann:' + str(code) + ':' + str(n)
    v = cache_get(key, ttl)
    if v is not None:
        return v
    try:
        import requests
        r = requests.get(LIST_API, params={'page_size': n, 'page_index': 1, 'ann_type': 'A',
                                           'client_source': 'web', 'stock_list': code}, headers=UA, timeout=15)
        rows = ((r.json().get('data') or {}).get('list')) or []
        out = [{'date': str(x.get('notice_date') or '')[:10], 'title': x.get('title') or '',
                'art': x.get('art_code'), 'url': (DETAIL + str(code) + '/' + str(x.get('art_code')) + '.html')} for x in rows]
    except Exception:
        out = []
    if out:
        cache_put(key, out)
    return out


def _content(art, ttl=86400):
    key = 'annc:' + str(art)
    v = cache_get(key, ttl)
    if v is not None:
        return v
    try:
        import requests
        r = requests.get(CONTENT_API, params={'art_code': art, 'client_source': 'web', 'page_index': 1},
                         headers=UA, timeout=15)
        body = ((r.json().get('data') or {}).get('notice_content')) or ''
    except Exception:
        body = ''
    if body:
        cache_put(key, body)
    return body


def classify(title):
    t = title or ''
    return [c for c, kws in CATS.items() if any(k in t for k in kws)]


def run(code, n=30, extract_n=4, use_llm=True):
    items = _list(code, n)
    for it in items:
        it['cats'] = classify(it['title'])
    counts = {}
    for it in items:
        for c in it['cats']:
            counts[c] = counts.get(c, 0) + 1
    picks = [it for it in items if it['cats']][:extract_n]
    for it in picks:
        body = _content(it['art'])
        it['content_len'] = len(body)
        it['fields'] = None
        if not body:
            it['extract_error'] = '正文为空'
            continue
        if use_llm:
            res = llm.chat([{'role': 'system', 'content': EXTRACT_SYS},
                            {'role': 'user', 'content': '公告标题：' + it['title'] + '\n正文：\n' + body[:7000]}],
                           temperature=0.1, max_tokens=700, timeout=120)
            txt = (res.get('text') or '').strip()
            i, j = txt.find('{'), txt.rfind('}')
            try:
                it['fields'] = json.loads(txt[i:j + 1]) if i >= 0 and j > i else None
            except Exception:
                it['fields'] = None
            if it['fields'] is None:
                it['extract_raw'] = txt[:300]
    return {'ok': True, 'code': code, 'total': len(items),
            'categories': counts, 'items': items, 'extracted': picks,
            'note': '正文来自东财公告全文；字段由 LLM 依据正文抽取，缺失为 null；原文证据为片段，请回原文核对'}
