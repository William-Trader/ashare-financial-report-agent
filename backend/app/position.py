# -*- coding: utf-8 -*-
"""持仓管理 + 风险敞口 + 仓位建议（投资辅助闭环）。"""
from . import realtime as rt, marketdata as md, scanner
from .datasource import to_em_symbol


def _advice(pnl_pct, risk_score, vol):
    """基于盈亏/风险分/波动的仓位建议。"""
    if risk_score is not None and risk_score >= 60:
        return '减仓', '综合风险分高，建议降低敞口'
    if pnl_pct is not None and pnl_pct <= -15:
        return '止损复核', '回撤超过 15%，核对止损纪律'
    if pnl_pct is not None and pnl_pct >= 30 and risk_score is not None and risk_score >= 30:
        return '止盈复核', '浮盈较大且风险中等，考虑分批止盈'
    if vol is not None and vol > 45:
        return '控制仓位', '年化波动偏高，建议降低单票权重'
    return '持有', '未见触发条件'


def analyze(items):
    """items: [{code, cost, qty, stop, target}]"""
    rows = []
    tot_cost = tot_val = 0.0
    for it in items or []:
        code = it.get('code')
        if not code:
            continue
        q = rt.quote(code)
        cost = it.get('cost')
        qty = it.get('qty')
        price = q.get('price') if q.get('ok') else None
        pnl = pnl_pct = None
        if price is not None and cost and qty:
            pnl = (price - float(cost)) * float(qty)
            pnl_pct = (price / float(cost) - 1) * 100
            tot_cost += float(cost) * float(qty)
            tot_val += price * float(qty)
        risk = None
        try:
            r = scanner.analyze(code, 6 * 3600, advanced=True, periods=2)
            risk = (r.get('risk') or {}).get('score')
        except Exception:
            pass
        vol = None
        try:
            k = md.daily(code, 120)
            if len(k) > 30:
                import statistics as st
                rets = [k[i]['close'] / k[i - 1]['close'] - 1 for i in range(1, len(k))]
                vol = round(st.pstdev(rets) * (252 ** 0.5) * 100, 1)
        except Exception:
            pass
        act, why = _advice(pnl_pct, risk, vol)
        rows.append({'code': to_em_symbol(code), 'name': q.get('name') or '', 'price': price,
                     'cost': cost, 'qty': qty, 'pnl': None if pnl is None else round(pnl, 2),
                     'pnl_pct': None if pnl_pct is None else round(pnl_pct, 2),
                     'market_value': None if (price is None or not qty) else round(price * float(qty), 2),
                     'risk_score': risk, 'annual_vol': vol,
                     'stop': it.get('stop'), 'target': it.get('target'),
                     'advice': act, 'reason': why})
    tot_pnl = tot_val - tot_cost if tot_cost else None
    rows.sort(key=lambda x: -(x['pnl'] or 0))
    return {'ok': True, 'items': rows,
            'summary': {'total_cost': round(tot_cost, 2), 'total_value': round(tot_val, 2),
                        'total_pnl': None if tot_pnl is None else round(tot_pnl, 2),
                        'total_pnl_pct': None if not tot_cost else round(tot_pnl / tot_cost * 100, 2),
                        'count': len(rows)},
            'note': '盈亏按最新行情计算；仓位建议基于风险分/波动/盈亏触发条件，非投资建议'}
