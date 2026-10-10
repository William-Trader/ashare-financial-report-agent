# -*- coding: utf-8 -*-
"""工程化护栏：外部抓取必须有超时 + 本地兜底，防止单个被限流的接口拖死整站。

设计铁律（见 docs/ENGINEERING.md）：
  1) 任何网络抓取都必须走 with_timeout（默认 8s），绝不裸调；
  2) 超时/失败时必须回退到本地缓存或仓库（降级但可用）；
  3) 每次超时/回退都写 guard.log 并计数，供 /api/reliability 观测。
"""
import os, threading, time

DATA_DIR = os.environ.get('FR_DATA_DIR', '/home/ubuntu/fr-agent/data')
LOG = os.path.join(DATA_DIR, 'guard.log')
_LOCK = threading.Lock()
STATS = {'timeouts': 0, 'fallbacks': 0, 'incidents': [], 'boot': time.time()}


def _log(kind, label):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG, 'a') as f:
            f.write('%s %s %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), kind, label))
    except Exception:
        pass


def _incident(kind, label):
    with _LOCK:
        if kind == 'timeout':
            STATS['timeouts'] += 1
        else:
            STATS['fallbacks'] += 1
        STATS['incidents'].append({'ts': round(time.time(), 1), 'type': kind, 'label': label})
        STATS['incidents'] = STATS['incidents'][-80:]
    _log(kind.upper(), label)


def with_timeout(fn, timeout=8, default=None, label='fetch'):
    """在守护线程里执行 fn；超时返回 default（并记一次超时）。绝不阻塞调用方。"""
    box = {'v': default, 'done': False}

    def run():
        try:
            box['v'] = fn()
        except Exception:
            pass
        box['done'] = True

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if not box['done']:
        _incident('timeout', '%s(>%ss)' % (label, timeout))
        return default
    return box['v']


def note_fallback(label):
    _incident('fallback', label)


def stats():
    with _LOCK:
        s = dict(STATS)
        s['incidents'] = list(STATS['incidents'][-30:])
    s['log'] = LOG
    return s
