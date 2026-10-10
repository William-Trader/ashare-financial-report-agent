# -*- coding: utf-8 -*-
"""全量数据拉取任务：后台批量灌入三表/指标/K线，支持进度、暂停、断点续跑。"""
import os, json, threading, time, traceback
from . import warehouse, scanner, marketdata
from .datasource import to_em_symbol, cache_get, cache_put

DATA_DIR = os.environ.get('FR_DATA_DIR', '/home/ubuntu/fr-agent/data')
FLAG = os.path.join(DATA_DIR, 'syncjob.active')


def _flag_set(on, workers=None, with_kline=None):
    """意图标志同时持久化参数，续跑时保持同样的并发/口径。"""
    try:
        if on:
            with open(FLAG, 'w') as f:
                json.dump({'ts': int(time.time()), 'workers': workers or 6, 'with_kline': bool(with_kline)}, f)
        elif os.path.exists(FLAG):
            os.remove(FLAG)
    except Exception:
        pass


def _flag_read():
    try:
        with open(FLAG) as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {'workers': 6, 'with_kline': True}
    except Exception:
        return {'workers': 6, 'with_kline': True}


def resume_if_needed():
    """服务重启后自动续跑（默认关闭：批量灌数会抢 CPU/内存，拖慢网页）。
    需要时设环境变量 FR_SYNC_AUTORESUME=1 开启。"""
    if os.environ.get('FR_SYNC_AUTORESUME') != '1':
        return {'ok': False, 'reason': 'autoresume disabled'}
    if os.path.exists(FLAG) and not STATE['running']:
        cfg = _flag_read()
        return start(None, cfg.get('workers', 6), cfg.get('with_kline', True))
    return {'ok': False, 'reason': 'no intent flag'}

LOCK = threading.Lock()
STATE = {
    'running': False, 'stop': False, 'total': 0, 'done': 0, 'failed': 0,
    'current': '', 'started_at': None, 'finished_at': None, 'errors': [],
    'with_kline': True, 'workers': 3, 'phase': 'idle',
}


def status():
    with LOCK:
        s = dict(STATE)
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


def _codes(limit=None, only_missing=True):
    d, rows = warehouse.market_snap()
    codes = [r['code'] for r in rows]
    if only_missing:
        have = set()
        try:
            with warehouse.cursor() as c:
                for (cd,) in c.execute('SELECT DISTINCT code FROM statements').fetchall():
                    have.add(str(cd)[2:] if len(str(cd)) > 6 else str(cd))
        except Exception:
            pass
        codes = [c for c in codes if c not in have]
    if limit:
        codes = codes[:int(limit)]
    return codes


def _worker(chunk, with_kline):
    for code in chunk:
        if STATE['stop']:
            return
        with LOCK:
            STATE['current'] = code
        try:
            scanner.analyze(code, 6 * 3600, advanced=False, periods=8)
            if with_kline:
                marketdata.daily(code, 250)
            with LOCK:
                STATE['done'] += 1
        except Exception as e:
            with LOCK:
                STATE['failed'] += 1
                if len(STATE['errors']) < 20:
                    STATE['errors'].append(code + ': ' + str(e)[:100])
        time.sleep(0.15)


def _run(limit, workers, with_kline):
    try:
        codes = _codes(limit)
        with LOCK:
            STATE.update({'total': len(codes), 'done': 0, 'failed': 0, 'phase': 'running'})
        n = max(1, min(int(workers or 3), 6))
        chunks = [codes[i::n] for i in range(n)]
        ths = [threading.Thread(target=_worker, args=(ch, with_kline), daemon=True) for ch in chunks]
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
        # 仅当「用户显式停止」或「已跑完」才清除意图；被重启打断则保留 → 下次启动续跑
        if stopped or (total and done >= total):
            _flag_set(False)


def start(limit=None, workers=3, with_kline=True):
    with LOCK:
        if STATE['running']:
            return {'ok': False, 'reason': '任务已在运行', 'status': dict(STATE)}
        STATE.update({'running': True, 'stop': False, 'started_at': time.time(),
                      'finished_at': None, 'errors': [], 'with_kline': bool(with_kline),
                      'workers': int(workers or 3), 'phase': 'starting'})
    _flag_set(True, workers, with_kline)
    t = threading.Thread(target=_run, args=(limit, workers, with_kline), daemon=True)
    t.start()
    return {'ok': True, 'status': status()}


def stop():
    with LOCK:
        STATE['stop'] = True
    _flag_set(False)   # 用户显式停止 → 清除意图
    return {'ok': True, 'status': status()}
