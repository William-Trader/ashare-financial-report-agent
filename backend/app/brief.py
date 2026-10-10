# -*- coding: utf-8 -*-
"""一键投研简报：把行情/财务/风险/估值/事件/建议汇总成可读简报。"""
import time
from . import realtime as rt, marketdata, valuation, scanner, events as events_mod, suggest as suggest_mod


def _fmt(v, unit=''):
    if v is None:
        return '—'
    a = abs(v)
    if a >= 1e8:
        return str(round(v / 1e8, 2)) + '亿' + unit
    if a >= 1e4:
        return str(round(v / 1e4, 2)) + '万' + unit
    return str(round(v, 2)) + unit


def run(code):
    out = {'code': code, 'generated': time.time()}
    r = scanner.analyze(code, 6 * 3600, advanced=True, periods=8)
    rep = r['report']
    inc = r['indicators']['rows'][0]['indices'] if r['indicators']['rows'] else {}
    q = rt.quote(code)
    pf = marketdata.profile(code)
    va = valuation.run(code)
    sg = suggest_mod.build(r, with_llm=False)
    ev = events_mod.all_events(code)
    out['name'] = rep.get('name')
    out['period'] = rep.get('period')
    L = []
    L.append('# ' + str(rep.get('name')) + '（' + str(rep.get('code')) + '）投研简报')
    L.append('生成时间：' + time.strftime('%Y-%m-%d %H:%M'))
    L.append('')
    if q.get('ok'):
        L.append('## 一、实时行情')
        L.append('- 最新价 ' + str(q['price']) + '，涨跌 ' + str(q.get('changePct')) + '%')
        L.append('- 市盈率 ' + _fmt(q.get('pe')) + '，市净率 ' + _fmt(q.get('pb')) + '，总市值 ' + _fmt(q.get('marketCap')))
    if pf.get('ok'):
        L.append('- 行业：' + str(pf.get('industry')) + '（' + str(pf.get('industry_csrc')) + '）')
    L.append('')
    L.append('## 二、财务概览（' + str(rep.get('period')) + '）')
    L.append('- 毛利率 ' + _fmt(inc.get('毛利率%'), '%') + '，归母净利率 ' + _fmt(inc.get('归母净利率%'), '%') + '，ROE ' + _fmt(inc.get('ROE(归母权益)%'), '%'))
    L.append('- 单季营收同比 ' + _fmt(inc.get('单季营收同比%'), '%') + '，单季归母净利同比 ' + _fmt(inc.get('单季归母净利同比%'), '%'))
    L.append('- 净现比 ' + _fmt(inc.get('净现比')) + '，收现比 ' + _fmt(inc.get('收现比')) + '，资产负债率 ' + _fmt(inc.get('资产负债率%'), '%'))
    if va.get('ok'):
        L.append('')
        L.append('## 三、估值位置')
        L.append('- PE ' + _fmt(va.get('pe')) + '（历史分位 ' + _fmt(va.get('pe_percentile'), '%') + '）')
        L.append('- PB ' + _fmt(va.get('pb')) + '（历史分位 ' + _fmt(va.get('pb_percentile'), '%') + '）')
    L.append('')
    L.append('## 四、风险与异常')
    rk = r.get('risk') or {}
    L.append('- 综合风险评分 ' + str(rk.get('score')) + '（' + str(rk.get('level')) + '）')
    for d in (rk.get('drivers') or [])[:4]:
        L.append('  - ' + d['name'] + '：' + d['detail'])
    anm = r.get('anomalies') or []
    if not anm:
        L.append('- 未发现显著异常信号')
    L.append('')
    L.append('## 五、事件与资金')
    for it in (ev.get('items') or [])[:5]:
        L.append('- [' + str(it.get('source')) + '] ' + str(it.get('date')) + ' ' + str(it.get('title') or it.get('reason') or ''))
    L.append('')
    L.append('## 六、操作建议')
    L.append('- 倾向：**' + str(sg.get('action')) + '**（评分 ' + str(sg.get('score')) + '/100）')
    for x in (sg.get('reasons') or [])[:3]:
        L.append('  - ' + x)
    L.append('- 下一步：')
    for x in (sg.get('next_steps') or []):
        L.append('  - ' + x)
    L.append('')
    L.append('> 本简报由程序自动生成，数据来自东方财富/腾讯/akshare，仅供研究参考，不构成投资建议。')
    out['markdown'] = '\n'.join(L)
    out['sections'] = {'quote': q, 'profile': pf, 'valuation': va, 'risk': rk,
                       'anomalies': anm[:6], 'events': (ev.get('items') or [])[:8], 'suggest': sg}
    return out
