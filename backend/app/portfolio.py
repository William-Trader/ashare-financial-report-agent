# -*- coding: utf-8 -*-
"""组合风控（复刻老系统 portfolio.js 口径）：年化/波动/β/VaR/CVaR/最大回撤/风险贡献/最小方差/风险平价。"""
import numpy as np
from . import marketdata as md
from .datasource import to_em_symbol

BENCH = 'sh000001'  # 上证指数


def _returns(code, n):
    k = md.daily(code, n)
    if len(k) < 30:
        return None
    c = np.array([x['close'] for x in k], dtype=float)
    return c[1:] / c[:-1] - 1.0


def run(codes, weights=None, days=250, confidence=0.95):
    codes = [c for c in (codes or []) if c][:20]
    if not codes:
        return {'ok': False, 'error': '需要 codes'}
    days = max(60, min(int(days or 250), 500))
    R = []
    used = []
    for c in codes:
        r = _returns(c, days)
        if r is not None:
            R.append(r)
            used.append(c)
    if len(used) < 2:
        return {'ok': False, 'error': '有效标的不满 2 个'}
    m = min(len(r) for r in R)
    R = np.array([r[-m:] for r in R])
    k = len(used)
    w = np.array(weights[:k], dtype=float) if weights and len(weights) >= k else np.ones(k) / k
    if w.sum() == 0:
        w = np.ones(k) / k
    w = w / w.sum()
    port = R.T @ w
    mean = R.mean(axis=1) * 252
    vol = R.std(axis=1, ddof=1) * np.sqrt(252)
    cov = np.cov(R, ddof=1)
    p_vol = float(np.sqrt(w @ cov @ w) * np.sqrt(252))
    p_mean = float(w @ mean)
    b = md.daily(BENCH, days)
    beta = None
    if b and len(b) > 30:
        bc = np.array([x['close'] for x in b], dtype=float)
        br = bc[1:] / bc[:-1] - 1.0
        L = min(len(br), m)
        covp = np.cov(port[-L:], br[-L:], ddof=1)
        beta = round(float(covp[0, 1] / covp[1, 1]), 3) if covp[1, 1] else None
    var = float(-np.percentile(port, (1 - confidence) * 100))
    tail = port[port <= -var]
    cvar = float(-tail.mean()) if len(tail) else var
    nav = np.cumprod(1 + port)
    dd = float((nav / np.maximum.accumulate(nav) - 1).min())
    rc = w * (cov @ w) / (w @ cov @ w) if (w @ cov @ w) else np.zeros(k)
    # 最小方差（解析：w ∝ Σ⁻¹1）
    minvar = None
    try:
        inv = np.linalg.inv(cov + np.eye(k) * 1e-10)
        ones = np.ones(k)
        mv = inv @ ones
        mv = mv / mv.sum()
        minvar = [round(float(x), 4) for x in mv]
    except Exception:
        pass
    # 风险平价（迭代）
    rp = np.ones(k) / k
    for _ in range(200):
        mrc = cov @ rp
        rp = rp * (1.0 / (mrc * k))
        rp = rp / rp.sum()
    rp = [round(float(x), 4) for x in rp]
    return {'ok': True, 'note': '无风险利率=0；算术年化(mean×252)；VaR 历史法；基准=上证指数',
            'codes': [to_em_symbol(c) for c in used], 'days': days, 'samples': int(m),
            'weights': [round(float(x), 4) for x in w],
            'annual_return': round(p_mean * 100, 2), 'annual_vol': round(p_vol * 100, 2),
            'sharpe': round(p_mean / p_vol, 3) if p_vol else None,
            'beta': beta, 'var': round(var * 100, 3), 'cvar': round(cvar * 100, 3),
            'max_drawdown': round(dd * 100, 2), 'confidence': confidence,
            'risk_contribution': [round(float(x) * 100, 2) for x in rc],
            'min_variance_weights': minvar, 'risk_parity_weights': rp,
            'per_asset': [{'code': to_em_symbol(used[i]), 'annual_return': round(float(mean[i]) * 100, 2),
                           'annual_vol': round(float(vol[i]) * 100, 2)} for i in range(k)]}
