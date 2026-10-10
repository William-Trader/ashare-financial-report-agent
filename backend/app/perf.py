# -*- coding: utf-8 -*-
"""性能层：进程内 TTL 缓存 + 计时统计。"""
import time
import threading
from functools import wraps

_LOCK = threading.Lock()
_CACHE = {}
_STATS = {'hits': 0, 'misses': 0, 'calls': {}}


def ttl_cache(seconds=300, key_fn=None):
    def deco(fn):
        @wraps(fn)
        def inner(*a, **kw):
            key = (fn.__name__, key_fn(*a, **kw) if key_fn else (a, tuple(sorted(kw.items()))))
            now = time.time()
            with _LOCK:
                item = _CACHE.get(key)
                if item and item[0] > now:
                    _STATS['hits'] += 1
                    return item[1]
                _STATS['misses'] += 1
            val = fn(*a, **kw)
            with _LOCK:
                _CACHE[key] = (now + seconds, val)
                if len(_CACHE) > 512:
                    for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:128]:
                        _CACHE.pop(k, None)
            return val
        return inner
    return deco


def timed(fn):
    @wraps(fn)
    def inner(*a, **kw):
        t0 = time.time()
        try:
            return fn(*a, **kw)
        finally:
            dt = time.time() - t0
            name = fn.__name__
            with _LOCK:
                d = _STATS['calls'].setdefault(name, {'n': 0, 'total': 0.0, 'max': 0.0})
                d['n'] += 1
                d['total'] += dt
                d['max'] = max(d['max'], dt)
    return inner


def stats():
    with _LOCK:
        calls = {k: {'n': v['n'], 'avg_ms': round(v['total'] / v['n'] * 1000, 1), 'max_ms': round(v['max'] * 1000, 1)}
                 for k, v in _STATS['calls'].items()}
        return {'cache_entries': len(_CACHE), 'hits': _STATS['hits'], 'misses': _STATS['misses'],
                'hit_rate': (round(_STATS['hits'] / max(1, _STATS['hits'] + _STATS['misses']) * 100, 1)),
                'slowest': sorted(calls.items(), key=lambda kv: -kv[1]['avg_ms'])[:12]}


def clear():
    with _LOCK:
        _CACHE.clear()
