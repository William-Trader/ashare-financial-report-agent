# -*- coding: utf-8 -*-
"""证据链 + 审计日志 + 合规元数据（复刻老系统 trust.js 的轻量版）。"""
import os, json, time, hashlib

DATA_DIR = os.environ.get('FR_DATA_DIR', '/home/ubuntu/fr-agent/data')
AUDIT = os.path.join(DATA_DIR, 'audit.jsonl')
EVID = os.path.join(DATA_DIR, 'evidence')


def _ensure():
    os.makedirs(EVID, exist_ok=True)


def audit(event, payload=None):
    _ensure()
    rec = {'ts': time.time(), 'iso': time.strftime('%Y-%m-%dT%H:%M:%S'), 'event': event,
           'digest': hashlib.md5(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:12],
           'payload': payload}
    try:
        with open(AUDIT, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')
    except Exception:
        pass
    return rec['digest']


def list_audit(limit=50):
    if not os.path.exists(AUDIT):
        return []
    out = []
    try:
        with open(AUDIT, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        return []
    return out[-limit:][::-1]


def save_evidence(analysis, code=None):
    _ensure()
    eid = 'e-' + hashlib.md5((str(code) + str(time.time())).encode()).hexdigest()[:10]
    rep = (analysis or {}).get('report') or {}
    rows = (analysis.get('indicators') or {}).get('rows') or []
    vals = rows[0].get('indices') if rows else {}
    ev = {'id': eid, 'code': rep.get('code'), 'name': rep.get('name'), 'period': rep.get('period'),
          'created': time.time(), 'checks_summary': rep.get('checks_summary'),
          'summary': rep.get('summary'), 'attribution': rep.get('attribution'),
          'values': vals, 'evidence': rep.get('evidence'),
          'compliance': {'source': '东方财富/akshare', 'as_of': time.strftime('%Y-%m-%dT%H:%M:%S'),
                         'disclaimer': '本分析由程序自动生成，仅供研究参考，不构成投资建议'}}
    try:
        with open(os.path.join(EVID, eid + '.json'), 'w', encoding='utf-8') as f:
            json.dump(ev, f, ensure_ascii=False, default=str)
    except Exception:
        pass
    audit('analyze:data', {'id': eid, 'code': ev['code'], 'period': ev['period']})
    return ev


def guard(markdown, evidence):
    """幻觉拦截：正文中的百分比/金额必须在证据（含真实数值池）里能找到。"""
    import re
    nums = re.findall(r'(\d+(?:\.\d+)?)\s*(%|亿|万|元)', markdown or '')
    pool = json.dumps(evidence, ensure_ascii=False, default=str)
    # 数值池同时容忍「亿/万」换算后的裸数字
    extra = set()
    for m2 in re.findall(r'\d+(?:\.\d+)?', pool):
        extra.add(m2)
    pool = pool + ' ' + ' '.join(extra)
    miss = []
    for n, u in nums[:60]:
        if n not in pool:
            miss.append(n + u)
    return {'checked': len(nums[:60]), 'unmatched': len(miss), 'samples': miss[:8],
            'level': 'ok' if len(miss) <= 2 else ('warn' if len(miss) <= 6 else 'high')}
