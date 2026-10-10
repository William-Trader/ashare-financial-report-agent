# -*- coding: utf-8 -*-
"""全市场财报统一分析（云端批处理）。

后台逐股跑确定性分析流水线（scanner.analyze）→ 压缩成研究记录 → 落库。
前端只读缓存结果，无需实时渲染；任务限流、可断点续跑，绝不饿死站点。
"""
import os, json, threading, time, traceback
from . import warehouse, scanner, tracks
from . import suggest as suggest_mod

FLAG = os.path.join(warehouse.DATA_DIR, 'research.active')
LOCK = threading.Lock()
STATE = {'running': False, 'stop': False, 'total': 0, 'done': 0, 'failed': 0,
         'current': '', 'started_at': None, 'finished_at': None, 'errors': [],
         'phase': 'idle', 'workers': 1}

KEY_FIELDS = ['毛利率%', '归母净利率%', 'ROE(归母权益)%', '资产负债率%', '净现比', '扣非占比%',
              '单季营收同比%', '单季归母净利同比%', '单季经营现金流同比%']


def _flag_set(on, workers=None, force=None):
    try:
        if on:
            with open(FLAG, 'w') as f:
                json.dump({'ts': int(time.time()), 'workers': workers or 1, 'force': bool(force)}, f)
        elif os.path.exists(FLAG):
            os.remove(FLAG)
    except Exception:
        pass


def coverage():
    try:
        with warehouse.cursor() as c:
            total = c.execute('SELECT COUNT(DISTINCT code) FROM market_snap').fetchone()[0]
            done = c.execute('SELECT COUNT(*) FROM research').fetchone()[0]
        return {'market_total': total, 'analyzed': done,
                'pct': round(100.0 * done / total, 2) if total else 0}
    except Exception as e:
        return {'error': str(e)[:120]}


def status():
    with LOCK:
        s = dict(STATE)
    s['coverage'] = coverage()
    if s['running'] and s['started_at'] and s['done']:
        el = time.time() - s['started_at']
        rate = s['done'] / el if el else 0
        left = s['total'] - s['done']
        s['eta_sec'] = round(left / rate, 1) if rate > 0 else None
        s['rate_per_min'] = round(rate * 60, 1)
    else:
        s['eta_sec'] = None
        s['rate_per_min'] = None
    return s


def _snap_map():
    d, rows = warehouse.market_snap()
    return {r['code']: r for r in rows}


def _codes(limit=None, force=False):
    _, rows = warehouse.market_snap()
    rows = sorted(rows, key=lambda r: abs(r.get('np_yoy') or 0), reverse=True)
    have = set()
    if not force:
        try:
            with warehouse.cursor() as c:
                have = set(x[0] for x in c.execute('SELECT code FROM research').fetchall())
        except Exception:
            pass
    codes = [r['code'] for r in rows if r['code'] not in have]
    if limit:
        codes = codes[:int(limit)]
    return codes


def analyze_one(code, snap=None):
    r = scanner.analyze(code, 6 * 3600, advanced=True, periods=6)
    rep = r.get('report') or {}
    err = r.get('error') or rep.get('error')
    if err:
        raise RuntimeError(str(err)[:140])
    inc = (r.get('indicators') or {}).get('rows') or []
    idx = inc[0]['indices'] if inc and inc[0].get('indices') else {}
    rk = r.get('risk') or {}
    sug = suggest_mod.build(r, with_llm=False)
    row = snap or {}
    tk, tkn = 'other', '均衡其他'
    for t in tracks.TRACKS:
        try:
            if t['rule'](row):
                tk, tkn = t['key'], t['name']
                break
        except Exception:
            pass
    return {
        'code': code, 'name': rep.get('name') or row.get('name'), 'period': rep.get('period'),
        'risk_score': rk.get('score'), 'risk_level': rk.get('level'),
        'verdict': sug.get('action'), 'tone': sug.get('tone'),
        'track': tk, 'track_name': tkn,
        'key': {k: idx.get(k) for k in KEY_FIELDS},
        'anomalies': [{'类别': a['category'], '期间': a['period'], '说明': a['title']}
                      for a in (r.get('anomalies') or [])],
        'checks': rep.get('checks_summary'),
    }


def _save(rec):
    with warehouse.cursor() as c:
        c.execute('INSERT OR REPLACE INTO research (code, name, period, risk_score, risk_level, verdict, tone, track, track_name, key_json, anomalies_json, checks_json, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (rec['code'], rec.get('name'), rec.get('period'), rec.get('risk_score'), rec.get('risk_level'),
                   rec.get('verdict'), rec.get('tone'), rec.get('track'), rec.get('track_name'),
                   json.dumps(rec.get('key') or {}, ensure_ascii=False),
                   json.dumps(rec.get('anomalies') or [], ensure_ascii=False),
                   json.dumps(rec.get('checks') or {}, ensure_ascii=False), time.time()))


def _worker(chunk, snaps):
    for code in chunk:
        if STATE['stop']:
            return
        with LOCK:
            STATE['current'] = code
        try:
            rec = analyze_one(code, snaps.get(code))
            _save(rec)
            with LOCK:
                STATE['done'] += 1
        except Exception as e:
            with LOCK:
                STATE['failed'] += 1
                if len(STATE['errors']) < 20:
                    STATE['errors'].append(code + ': ' + str(e)[:100])
        time.sleep(0.2)


def _run(limit, workers, force):
    try:
        codes = _codes(limit, force)
        snaps = _snap_map()
        with LOCK:
            STATE.update({'total': len(codes), 'done': 0, 'failed': 0, 'phase': 'running'})
        n = max(1, min(int(workers or 1), 3))
        chunks = [codes[i::n] for i in range(n)]
        ths = [threading.Thread(target=_worker, args=(ch, snaps), daemon=True) for ch in chunks]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
    except Exception:
        with LOCK:
            STATE['errors'].append(traceback.format_exc()[-300:])
    finally:
        with LOCK:
            STATE['running'] = False
            STATE['phase'] = 'done'
            STATE['finished_at'] = time.time()
            STATE['current'] = ''
            stopped = STATE['stop']
            done, total = STATE['done'], STATE['total']
        if stopped or (total and done >= total):
            _flag_set(False)


def start(limit=None, workers=1, force=False):
    with LOCK:
        if STATE['running']:
            return {'ok': False, 'reason': '任务已在运行', 'status': dict(STATE)}
        STATE.update({'running': True, 'stop': False, 'started_at': time.time(),
                      'finished_at': None, 'errors': [], 'workers': int(workers or 1),
                      'phase': 'starting'})
    _flag_set(True, workers, force)
    t = threading.Thread(target=_run, args=(limit, workers, force), daemon=True)
    t.start()
    return {'ok': True, 'status': status()}


def stop():
    with LOCK:
        STATE['stop'] = True
    return {'ok': True, 'status': status()}


def results(sort='risk', limit=100, level=None, track=None, verdict=None, q=''):
    sort_col = {'risk': 'risk_score', 'name': 'name', 'code': 'code'}.get(sort, 'risk_score')
    where, args = [], []
    if level:
        where.append('risk_level=?'); args.append(level)
    if track:
        where.append('track=?'); args.append(track)
    if verdict:
        where.append('verdict=?'); args.append(verdict)
    if q:
        where.append('(code LIKE ? OR name LIKE ?)'); args += ['%' + q + '%', '%' + q + '%']
    sql = 'SELECT code,name,period,risk_score,risk_level,verdict,tone,track,track_name,key_json,anomalies_json,updated_at FROM research'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY ' + sort_col + ' DESC LIMIT ?'
    args.append(max(1, min(int(limit or 100), 1000)))
    with warehouse.cursor() as c:
        rows = c.execute(sql, args).fetchall()
    items = []
    for r in rows:
        try:
            key = json.loads(r[9] or '{}')
            anm = json.loads(r[10] or '[]')
        except Exception:
            key, anm = {}, []
        items.append({'code': r[0], 'name': r[1], 'period': r[2], 'risk_score': r[3], 'risk_level': r[4],
                      'verdict': r[5], 'tone': r[6], 'track': r[7], 'track_name': r[8],
                      'key': key, 'anomalies': anm, 'updated_at': r[11]})
    return {'ok': True, 'count': len(items), 'items': items}


def summary():
    with warehouse.cursor() as c:
        total = c.execute('SELECT COUNT(*) FROM research').fetchone()[0]
        by_level = c.execute('SELECT risk_level, COUNT(*) FROM research GROUP BY risk_level').fetchall()
        by_verdict = c.execute('SELECT verdict, COUNT(*) FROM research GROUP BY verdict').fetchall()
        by_track = c.execute('SELECT track_name, COUNT(*) FROM research GROUP BY track_name').fetchall()
        top_risk = c.execute('SELECT code,name,risk_score,risk_level,verdict FROM research ORDER BY risk_score DESC LIMIT 10').fetchall()
    return {'ok': True, 'analyzed': total,
            'by_level': [{'level': a, 'count': b} for a, b in by_level],
            'by_verdict': [{'verdict': a, 'count': b} for a, b in by_verdict],
            'by_track': [{'track': a, 'count': b} for a, b in by_track],
            'top_risk': [{'code': a, 'name': b, 'score': c, 'level': d, 'verdict': e} for a, b, c, d, e in top_risk]}


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _pct_rank(vals, v):
    xs = [x for x in vals if x is not None]
    if not xs or v is None:
        return None
    return round(100.0 * sum(1 for x in xs if x <= v) / len(xs), 1)


def _median(vals):
    xs = sorted(x for x in vals if x is not None)
    if not xs:
        return None
    n = len(xs)
    return round(xs[n // 2], 2) if n % 2 else round((xs[n // 2 - 1] + xs[n // 2]) / 2.0, 2)


def peer(code):
    """赛道对标：该公司在其财报赛道内的关键指标分位 + 同赛道风险名单。"""
    with warehouse.cursor() as c:
        row = c.execute('SELECT code,name,track,track_name,risk_score,key_json FROM research WHERE code=?', (code,)).fetchone()
        if not row:
            return {'ok': False, 'reason': '该公司尚未完成云端分析（可在「全市场分析库」启动批量分析后重试）'}
        _code, name, track, tname, rscore, key_json = row
        peers = c.execute('SELECT code,name,risk_score,key_json FROM research WHERE track=? AND code<>?', (track, code)).fetchall()
    try:
        mykey = json.loads(key_json or '{}')
    except Exception:
        mykey = {}
    metrics = ['ROE(归母权益)%', '毛利率%', '净现比', '单季营收同比%', '单季归母净利同比%']
    pk = []
    for p in peers:
        try:
            pk.append(json.loads(p[3] or '{}'))
        except Exception:
            pk.append({})
    ranks = {}
    for m in metrics:
        vals = [k.get(m) for k in pk]
        ranks[m] = {'值': _num(mykey.get(m)), '分位': _pct_rank(vals, mykey.get(m)), '同业中位': _median(vals)}
    top = sorted([{'code': p[0], 'name': p[1], 'risk_score': p[2]} for p in peers], key=lambda x: -(x['risk_score'] or 0))[:10]
    return {'ok': True, 'code': _code, 'name': name, 'track': track, 'track_name': tname,
            'risk_score': rscore, 'peer_count': len(peers), 'ranks': ranks, 'top_risk_peers': top}
