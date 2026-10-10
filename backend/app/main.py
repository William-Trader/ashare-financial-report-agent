# -*- coding: utf-8 -*-
"""财报分析智能体 · API 服务。"""
import os, tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
import json
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import time
from pydantic import BaseModel
from typing import List, Optional
from . import normalize, indicators, checks as checks_mod, anomaly, report as report_mod, pdf_extract, store, scanner, llm, profile, market, suggest, datasource as ds, realtime as rt, events as events_mod, dividend as dividend_mod, marketdata, valuation, portfolio as portfolio_mod, roundtable as roundtable_mod, track as track_mod, trust, warehouse, screener, perf, checkup, factors, attribution, position, brief as brief_mod, syncjob, qqbot, deep, thesis, caliber, announce as announce_mod, valuation_model, report_check

START_TS = time.time()

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND = os.path.join(BASE, 'frontend')

app = FastAPI(title='财报分析智能体', version='0.2.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
app.add_middleware(GZipMiddleware, minimum_size=900)


@app.middleware('http')
async def _cache_headers(request: Request, call_next):
    resp = await call_next(request)
    p = request.url.path
    if p.startswith('/static/') and resp.status_code == 200:
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    elif p in ('/', '/index.html'):
        resp.headers['Cache-Control'] = 'no-cache'
    return resp


def _akey(code, ttl=6 * 3600, advanced=True, periods=12):
    return (normalize.to_em_symbol(code), advanced, periods)


@perf.ttl_cache(120, key_fn=_akey)
def analyze_cached(code, ttl=6 * 3600, advanced=True, periods=12):
    return scanner.analyze(code, ttl, advanced, periods)


def _wrap(code, ttl, advanced=True, periods=12):
    try:
        return analyze_cached(code, ttl, advanced, periods)
    except Exception as e:
        raise HTTPException(status_code=502, detail='数据源错误: ' + str(e)[:200])


@app.on_event('startup')
def _on_startup():
    try:
        syncjob.resume_if_needed()
    except Exception:
        pass
    try:
        c = qqbot.load_cfg()
        if c.get('app_id') and c.get('client_secret'):
            qqbot.ws_start()
    except Exception:
        pass
    try:
        import threading as _th
        _th.Thread(target=lambda: _bootstrap_payload(), daemon=True).start()   # 预热首屏数据，避免首次加载等冷缓存
    except Exception:
        pass
    try:
        import threading as _th2

        def _warm_heavy():
            try:
                market_overview()
            except Exception:
                pass
            try:
                from . import tracks
                tracks.run('')
            except Exception:
                pass
            try:
                from . import backtest
                backtest.run_all()
            except Exception:
                pass
        _th2.Thread(target=_warm_heavy, daemon=True).start()   # 预热重计算接口（回测/摘要/赛道）
    except Exception:
        pass


@app.get('/api/optimize')
@perf.ttl_cache(3600)
def optimize_view(iterations: int = 12):
    """策略优化：训练期优化因子权重，留出期验证（防过拟合）。"""
    from . import optimize as opt
    return opt.optimize(iterations)


@app.get('/api/eval')
@perf.ttl_cache(3600)
def eval_view(draws: int = 400):
    """评估实验室：数百轮横截面 + 预测量效 + 造假案例命中。"""
    from . import eval_lab
    return eval_lab.all_eval(draws)


@app.get('/api/fraudcases')
@perf.ttl_cache(3600)
def fraudcases_view():
    """造假案例验证：红旗引擎在已知造假/暴雷公司上的表现。"""
    from . import fraudcases
    return fraudcases.run_cases()


@app.get('/api/audit-opinion/{code}')
def audit_opinion_view(code: str):
    from . import forensic_plus
    return forensic_plus.audit_opinion(code)


@app.get('/api/notes/{code}')
def notes_view(code: str):
    from . import forensic_plus
    return forensic_plus.notes_extract(code)


@app.get('/api/consistency/{code}')
def consistency_view(code: str):
    from . import forensic_plus
    return forensic_plus.consistency(code)


@app.get('/api/industry-bench/{code}')
def industry_bench_view(code: str):
    from . import forensic_plus
    return forensic_plus.industry_bench(code)


@app.get('/api/rem/{code}')
def rem_view(code: str):
    from . import forensic_plus
    return forensic_plus.rem(code)


@app.get('/api/strategy')
def strategy_view():
    """当前活跃策略（多期 walk-forward 优化得到，含训练/留出验证数字）。"""
    from . import strategy
    return {'ok': True, **strategy.info()}


@app.get('/api/cyclical/{code}')
def cyclical_view(code: str, price_yoy: float = None, commodity_share: float = 0.6):
    """周期股专项：量价拆分 / 情景压力测试 / 科目穿透 / 异常三级定性。"""
    from . import cyclical
    return cyclical.run(code, price_yoy=price_yoy, commodity_share=commodity_share)


@app.get('/api/about')
def about():
    """作品元信息：选题方向与能力边界。"""
    return {'ok': True, 'name': 'financial-report-claw', 'zh': '财报分析智能体',
            'topic': '上市公司财务报告分析',
            'positioning': '面向上市公司财务报告的独立自持分析智能体：三表加工、口径守卫、异常与背离识别、深析与估值、赛道分类与对比、无未来函数回测。',
            'modules': ['三表提取', '指标库', '勾稽校验', '异常识别', '财报体检', '财报深析', '红旗库',
                        '法证评分', '估值建模', '研报纠错', '财报赛道', '财报对比', '赛道对标', '多因子选股',
                        '因子分层', '组合风控', '圆桌研判', '结论校准', '云端批量分析', '自持 Agent', '无未来函数回测'],
            'version': '1.0'}


@app.get('/api/health')
def health():
    return {'ok': True, 'service': 'fr-agent', 'version': app.version}


@app.get('/api/stock/{code}/statements')
def statements(code: str, ttl: int = 6 * 3600):
    try:
        return normalize.canonical(code, ttl)
    except Exception as e:
        raise HTTPException(status_code=502, detail='数据源错误: ' + str(e)[:200])


@app.get('/api/stock/{code}/indicators')
def get_indicators(code: str, ttl: int = 6 * 3600):
    try:
        return indicators.compute(normalize.canonical(code, ttl))
    except Exception as e:
        raise HTTPException(status_code=502, detail='数据源错误: ' + str(e)[:200])


@app.get('/api/stock/{code}/checks')
def get_checks(code: str, ttl: int = 6 * 3600):
    try:
        return {'items': checks_mod.run(normalize.canonical(code, ttl))}
    except Exception as e:
        raise HTTPException(status_code=502, detail='数据源错误: ' + str(e)[:200])


@app.get('/api/stock/{code}/anomalies')
def get_anomalies(code: str, ttl: int = 6 * 3600):
    try:
        canon = normalize.canonical(code, ttl)
        return {'items': anomaly.run(canon, indicators.compute(canon))}
    except Exception as e:
        raise HTTPException(status_code=502, detail='数据源错误: ' + str(e)[:200])


@app.get('/api/stock/{code}/report')
def get_report(code: str, ttl: int = 6 * 3600):
    return _wrap(code, ttl)['report']


@app.get('/api/stock/{code}/analysis')
def get_analysis(code: str, ttl: int = 6 * 3600):
    return _wrap(code, ttl)


@app.get('/api/stock/{code}/advanced')
def get_advanced(code: str, ttl: int = 6 * 3600):
    r = _wrap(code, ttl)
    return {
        'code': r['report']['code'], 'name': r['report']['name'], 'period': r['report']['period'],
        'forensics': r.get('forensics'), 'bridge': r.get('bridge'), 'crosscheck': r.get('crosscheck'),
        'changepoints': r.get('changepoints'), 'risk': r.get('risk'), 'structure': r.get('structure'),
    }


@app.get('/api/market/snapshot')
def market_snapshot(date: str = '', ttl: int = 6 * 3600, force: int = 0,
                    limit: int = 200, board: str = '', category: str = ''):
    try:
        return market.snapshot(date, ttl, force=bool(force), limit=limit,
                               board=board or None, category=category or None)
    except Exception as e:
        raise HTTPException(status_code=502, detail='市场数据错误: ' + str(e)[:200])


@app.get('/api/quote/{code}')
def get_quote(code: str):
    return rt.quote(code)


@app.get('/api/market/indices')
def get_indices():
    return rt.indices()


class PortfolioReq(BaseModel):
    codes: List[str]
    weights: Optional[List[float]] = None
    days: int = 250
    confidence: float = 0.95


class TrackReq(BaseModel):
    code: str
    direction: str
    confidence: float = 0.5
    text: str = ''
    name: str = ''


class PosReq(BaseModel):
    code: str
    name: str = ''
    cost: Optional[float] = None
    qty: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None


@app.post('/api/sync/start')
def sync_start(limit: int = 0, workers: int = 3, kline: int = 1):
    return syncjob.start(limit or None, workers, bool(kline))


@app.get('/api/sync/status')
def sync_status():
    return syncjob.status()


@app.post('/api/sync/stop')
def sync_stop():
    return syncjob.stop()


class QQConfigReq(BaseModel):
    app_id: Optional[str] = None
    client_secret: Optional[str] = None
    app_token: Optional[str] = None
    bot_secret: Optional[str] = None


class QQSendReq(BaseModel):
    target_type: str = 'group'
    target_id: str = ''
    text: str = ''
    msg_id: Optional[str] = None


class QQCommandReq(BaseModel):
    text: str


@app.get('/api/qq/status')
def qq_status():
    return qqbot.status()


@app.post('/api/qq/config')
def qq_config(req: QQConfigReq):
    return qqbot.save_cfg(req.dict())


@app.post('/api/qq/test')
def qq_test(req: QQSendReq):
    if not req.target_id:
        return {'ok': False, 'error': '需要 target_id'}
    return qqbot.send(req.target_type, req.target_id, req.text or '财报分析智能体 · 连通性测试')


class AskReq(BaseModel):
    text: str
    session_key: Optional[str] = None


@app.post('/api/ask')
def api_ask(req: AskReq):
    """Agent 接管的对话入口：自然语言 -> fr-agent 自建 agent 核心 -> 自主调用本机 API。"""
    return qqbot.ask_agent(req.text, req.session_key or 'agent:main:web')


@app.post('/api/agent/ask')
def api_agent_ask(req: AskReq):
    """独立 agent 端点（financial report claw）：LLM + 工具 函数调用循环，不依赖 OpenClaw。"""
    from . import agent_core
    return agent_core.ask(req.text, req.session_key)


@app.get('/api/agent/tools')
def api_agent_tools():
    """列出 agent 可调用的财报工具（用于前端展示/审计）。"""
    from . import agent_core
    return {'tools': [t['function']['name'] for t in agent_core.TOOLS], 'stats': agent_core.stats()}


@app.get('/api/qq/agent/status')
def qq_agent_status():
    return qqbot.agent_status()


class QQAskReq(BaseModel):
    text: str
    session_key: Optional[str] = None


@app.post('/api/qq/agent/test')
def qq_agent_test(req: QQAskReq):
    return qqbot.ask_agent(req.text, req.session_key)


@app.post('/api/qq/ws/start')
def qq_ws_start(intents: int = 0):
    return qqbot.ws_start(intents or None)


@app.post('/api/qq/ws/stop')
def qq_ws_stop():
    return qqbot.ws_stop()


@app.get('/api/qq/ws/status')
def qq_ws_status():
    return qqbot.ws_status()


@app.post('/api/qq/command')
def qq_command(req: QQCommandReq):
    return {'ok': True, 'reply': qqbot.handle_command(req.text)}


@app.post('/api/qq/webhook')
async def qq_webhook(request: Request):
    """QQ 开放平台回调：签名校验 + op13 握手 + @机器人 消息回复。"""
    raw = await request.body()
    ts = request.headers.get('X-Signature-Timestamp') or request.headers.get('x-signature-timestamp')
    sig = request.headers.get('X-Signature-Ed25519') or request.headers.get('x-signature-ed25519')
    try:
        payload = json.loads(raw.decode('utf-8') or '{}')
    except Exception:
        return {'ok': False, 'error': 'invalid json'}
    if payload.get('op') == 13:
        d = payload.get('d') or {}
        return qqbot.sign_validation(d.get('plain_token'), d.get('event_ts'))
    if sig and not qqbot.verify_signature(ts, raw, sig):
        return {'ok': False, 'error': '签名校验失败'}
    try:
        d = payload.get('d') or {}
        content = (d.get('content') or '').strip()
        author = (d.get('author') or {})
        reply = qqbot.handle_command(content)
        out = {'reply': reply}
        gid = d.get('group_openid')
        uid = author.get('user_openid') or author.get('member_openid')
        mid = d.get('id')
        if gid:
            out['sent'] = qqbot.send('group', gid, reply, mid)
        elif uid:
            out['sent'] = qqbot.send('user', uid, reply, mid)
        return out
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200]}


@app.get('/api/positions')
def positions():
    return {'items': store.pos_list(), 'analysis': position.analyze(store.pos_list())}


@app.post('/api/positions')
def pos_add(req: PosReq):
    store.pos_upsert(req.code, req.name, req.cost, req.qty, req.stop, req.target)
    return {'items': store.pos_list(), 'analysis': position.analyze(store.pos_list())}


@app.delete('/api/positions/{code}')
def pos_del(code: str):
    store.pos_del(code)
    return {'items': store.pos_list(), 'analysis': position.analyze(store.pos_list())}


@app.get('/api/brief/{code}')
def get_brief(code: str):
    return brief_mod.run(code)


@app.get('/api/valuation_model/{code}')
def get_valuation_model(code: str, wacc: float = 0.09, g1: float = 0.08, years: int = 5, g_term: float = 0.03):
    """自动化估值建模：DCF(FCFF) + 相对估值 + 敏感性矩阵。"""
    return valuation_model.run(code, wacc, g1, years, g_term)


class ReportCheckReq(BaseModel):
    code: str
    draft: str
    llm: int = 1


@app.post('/api/report_check')
def post_report_check(req: ReportCheckReq):
    """研报纠错核查：逐条比对草稿数字/口径/期间与系统事实。"""
    return report_check.run(req.code, req.draft, bool(req.llm))


@app.get('/api/announce/{code}')
def get_announce(code: str, n: int = 30, extract: int = 4, llm: int = 1):
    """公告结构化提取（质押/中标/股权变动/减值/诉讼/担保…），补上定期报告的滞后。"""
    return announce_mod.run(code, n, extract, bool(llm))


@app.get('/api/caliber/{code}')
def get_caliber(code: str, ttl: int = 6 * 3600):
    """口径守卫：声明口径 + 边界告警（金融股/中期未年化/单季不可推算/同比基准缺失等）。"""
    r = _wrap(code, ttl, advanced=False)
    ind = ''
    try:
        ind = (marketdata.profile(code) or {}).get('industry') or ''
    except Exception:
        pass
    return caliber.run(r['canonical'], r['indicators'], ind)


@app.get('/api/thesis/{code}')
def get_thesis(code: str, deep: int = 1):
    """投资逻辑闭环（深度推演，默认走推理档模型）。"""
    return thesis.run(code, use_deep=bool(deep))


@app.get('/api/finance/{code}')
def get_finance_deep(code: str, ttl: int = 6 * 3600):
    r = _wrap(code, ttl, advanced=False)
    return deep.run(r['canonical'], r['indicators'])


@app.get('/api/checkup/{code}')
def get_checkup(code: str, ttl: int = 6 * 3600):
    r = _wrap(code, ttl, advanced=False)
    return checkup.run(r['canonical'], r['indicators'])


@app.get('/api/reliability')
def reliability():
    """工程护栏观测：外部抓取超时/回退事件、运行时长。"""
    from . import safe
    return safe.stats()


@app.get('/api/market/overview')
@perf.ttl_cache(180)
def market_overview():
    """总览图表聚合：指数 + 市场情绪 + 板块 + 财报赛道 + 风险分布 + 大盘资金流。"""
    from . import tracks, research
    out = {'ok': True}
    try:
        out['indices'] = rt.indices()
    except Exception:
        out['indices'] = {'ok': False}
    try:
        out['index_sparks'] = rt.index_sparks()
    except Exception:
        out['index_sparks'] = {'ok': False}
    try:
        d = _wh_digest()
        out['date'] = d.get('date'); out['stats'] = d.get('stats'); out['board'] = d.get('board')
    except Exception:
        out['stats'] = None
    try:
        tr = tracks.run('')
        out['tracks'] = tr.get('summary') if tr.get('ok') else []
    except Exception:
        out['tracks'] = []
    try:
        out['research'] = research.summary()
        out['coverage'] = research.coverage()
    except Exception:
        out['research'] = None
    try:
        _dd, _rows = warehouse.market_snap()
        agg = {}
        for r in _rows:
            _b = r.get('board') or '其他'
            a = agg.setdefault(_b, {'board': _b, '暴雷': 0, '爆发': 0, '亏损': 0})
            tg = r.get('tag') or ''
            if '暴雷' in tg:
                a['暴雷'] += 1
            if '爆发' in tg:
                a['爆发'] += 1
            if '亏损' in tg:
                a['亏损'] += 1
        out['board_signals'] = sorted(agg.values(), key=lambda x: -(x['暴雷'] + x['爆发'] + x['亏损']))[:8]
    except Exception:
        out['board_signals'] = []
    out['fundflow'] = {'ok': False, 'note': 'index fund-flow endpoint unreachable from this host; chart uses local board signals instead'}
    return out


@app.get('/api/factors')
@perf.ttl_cache(600)
def get_factors(date: str = '', factor: str = 'score'):
    return factors.run(date or None, factor)


class AttributionReq(BaseModel):
    codes: List[str]
    weights: Optional[List[float]] = None
    days: int = 60


@app.post('/api/attribution')
def post_attribution(req: AttributionReq):
    return attribution.run(req.codes, req.weights, req.days)


@perf.ttl_cache(240, key_fn=lambda ttl=6 * 3600: ('bootstrap',))
def _wh_digest(date=None):
    """从本地仓库构建市场摘要（不依赖 akshare，快且稳）。"""
    try:
        d, rows = warehouse.market_snap(date)
    except Exception as e:
        return {'available': False, 'reason': str(e)[:120]}
    if not rows:
        return {'available': False, 'reason': '仓库暂无快照'}
    def tg(r):
        return r.get('tag') or ''
    stats = {'total': len(rows),
             '异动': sum(1 for r in rows if tg(r)),
             '暴雷': sum(1 for r in rows if '暴雷' in tg(r)),
             '爆发': sum(1 for r in rows if '爆发' in tg(r)),
             '亏损': sum(1 for r in rows if '亏损' in tg(r))}
    bd = {}
    for r in rows:
        bname = r.get('board') or '其他'
        e = bd.setdefault(bname, {'board': bname, 'total': 0, '异动': 0, '暴雷': 0})
        e['total'] += 1
        if tg(r):
            e['异动'] += 1
        if '暴雷' in tg(r):
            e['暴雷'] += 1
    board = [{'board': e['board'], 'total': e['total'], '异动': e['异动'], '暴雷': e['暴雷'],
              'ratio': round(100.0 * e['异动'] / e['total'], 1) if e['total'] else 0} for e in bd.values()]
    board.sort(key=lambda x: -x['ratio'])
    anom = sorted([r for r in rows if tg(r)], key=lambda r: -abs(r.get('np_yoy') or 0))[:15]
    top = [{'code': r['code'], 'name': r['name'], 'board': r.get('board'),
            'np_yoy': r.get('np_yoy'), 'rev_yoy': r.get('rev_yoy'),
            'tags': [[t, 'warn'] for t in tg(r).split('|') if t]} for r in anom]
    st = stats
    lines = ['报告期 ' + str(d) + '：全市场 ' + str(st['total']) + ' 家，异动 ' + str(st['异动']) + ' 家（本地仓库快照）。',
             '净利暴雷 ' + str(st['暴雷']) + '，净利爆发 ' + str(st['爆发']) + '，亏损 ' + str(st['亏损']) + '。']
    return {'available': True, 'date': d, 'stats': st, 'board': board, 'top': top, 'text': '\n'.join(lines), 'source': 'warehouse'}


def _bootstrap_payload(ttl=6 * 3600):
    out = {'ok': True, 'ts': time.time()}
    try:
        out['indices'] = rt.indices(120)
    except Exception as e:
        out['indices'] = {'ok': False, 'error': str(e)[:120]}
    try:
        out['digest'] = _wh_digest()
    except Exception as e:
        out['digest'] = {'available': False, 'reason': str(e)[:120]}
    try:
        out['metrics'] = {'watchlist': len(store.list_watch()), 'alerts': len(store.list_alerts(1000))}
    except Exception:
        pass
    return out


@app.get('/api/bootstrap')
@perf.ttl_cache(600)
def api_bootstrap(ttl: int = 6 * 3600):
    """首屏聚合（进程内缓存 4 分钟）：一次请求拿到指数 + 市场摘要，供页面「刷新即显」。"""
    try:
        out = dict(_bootstrap_payload(ttl))
        out['ts'] = time.time()
        out['cached'] = True
        return out
    except Exception as e:
        return {'ok': False, 'error': str(e)[:150]}


@app.get('/api/perf')
def perf_stats():
    return perf.stats()


@app.post('/api/perf/clear')
def perf_clear():
    perf.clear()
    return {'ok': True}


@app.get('/api/warehouse/stats')
def warehouse_stats():
    return warehouse.stats()


@app.post('/api/warehouse/sync')
def warehouse_sync(date: str = '', stocks: int = 0):
    """同步全市场快照；stocks>0 时再落盘前 N 只异动股的财报与K线。"""
    snap = market.snapshot(date, 6 * 3600, force=True)
    done = 0
    if stocks and snap.get('available'):
        for r in (snap.get('anomalies') or [])[:max(0, min(stocks, 40))]:
            try:
                scanner.analyze(r['code'], 6 * 3600)
                marketdata.daily(r['code'], 250)
                done += 1
            except Exception:
                pass
    return {'ok': True, 'date': snap.get('date'), 'market_rows': snap.get('stats', {}).get('total'),
            'stocks_synced': done, 'stats': warehouse.stats()}


@app.get('/api/warehouse/kline/{code}')
def warehouse_kline(code: str):
    return {'code': code, 'items': warehouse.kline(normalize.to_em_symbol(code)[2:])}


@app.get('/api/screener')
@perf.ttl_cache(180)
def run_screener(min_np_yoy: float = None, min_rev_yoy: float = None, min_roe: float = None,
                 min_gm: float = None, max_gm: float = None, boards: str = '', exclude_tags: str = '',
                 require_tags: str = '', sort: str = 'score', limit: int = 100, min_score: float = None,
                 date: str = ''):
    def sp(s):
        return [x.strip() for x in (s or '').split(',') if x.strip()]
    return screener.run(date or None, min_np_yoy, min_rev_yoy, min_roe, min_gm, max_gm,
                        sp(boards), sp(exclude_tags), sp(require_tags), sort, limit, min_score)


@app.get('/api/profile/{code}')
def get_profile(code: str):
    return marketdata.profile(code)


@app.get('/api/kline/{code}')
def get_kline(code: str, n: int = 250):
    return {'code': code, 'items': marketdata.daily(code, n)}


@app.get('/api/valuation/{code}')
def get_valuation(code: str, n: int = 250):
    return valuation.run(code, n)


@app.post('/api/portfolio/risk')
def portfolio_risk(req: PortfolioReq):
    return portfolio_mod.run(req.codes, req.weights, req.days, req.confidence)


@app.get('/api/roundtable/{code}')
def roundtable(code: str):
    return roundtable_mod.run(code)


@app.get('/api/track')
def track_list():
    return {'items': track_mod.stats() and store.track_all(), 'stats': track_mod.stats()}


@app.post('/api/track/register')
def track_register(req: TrackReq):
    return track_mod.register(req.code, req.direction, req.confidence, req.text, req.name)


@app.post('/api/track/settle')
def track_settle():
    return {'settled': track_mod.settle(), 'stats': track_mod.stats()}


@app.get('/api/audit')
def audit_list(limit: int = 50):
    return {'items': trust.list_audit(limit)}


@app.get('/api/guard/{code}')
def guard(code: str):
    r = _wrap(code, 6 * 3600)
    ev = trust.save_evidence(r, code)
    nar = llm.narrate(r)
    return {'evidence_id': ev['id'], 'compliance': ev['compliance'],
            'guard': trust.guard(nar.get('text', ''), ev), 'narrative': nar.get('text', '')}


@app.get('/api/dividend/{code}')
def get_dividend(code: str):
    return dividend_mod.run(code)


@app.get('/api/events/{code}')
def get_events(code: str, days: int = 60):
    return events_mod.all_events(code, days)


@app.get('/api/fundflow/{code}')
def get_fundflow(code: str, lmt: int = 30):
    return rt.fundflow(code, lmt)


@app.get('/api/market/digest')
def market_digest(date: str = '', ttl: int = 6 * 3600):
    try:
        return market.digest(date, ttl)
    except Exception as e:
        raise HTTPException(status_code=502, detail='市场数据错误: ' + str(e)[:200])


@app.get('/api/tracks')
@perf.ttl_cache(600)
def get_tracks(date: str = ''):
    """财报赛道分类：把全市场按财报画像分入爆发增长/稳健成长/质量白马/现金奶牛/困境反转/风险规避。"""
    from . import tracks
    return tracks.run(date)


class CompareReq(BaseModel):
    codes: List[str]


@app.post('/api/compare')
def compare_stocks(req: CompareReq):
    """财报对比：2-6 只标的并排（核心指标/同比/风险/估值）。"""
    from . import tracks
    return tracks.compare(req.codes)


@app.post('/api/research/start')
def research_start(limit: int = 0, workers: int = 1, force: bool = False):
    """启动全市场云端批量财报分析（后台，限流，可断点续跑）。"""
    from . import research
    return research.start(limit or None, workers, force)


@app.post('/api/research/stop')
def research_stop():
    from . import research
    return research.stop()


@app.get('/api/research/status')
def research_status():
    from . import research
    return research.status()


@app.get('/api/research/results')
def research_results(sort: str = 'risk', limit: int = 100, level: str = '', track: str = '', verdict: str = '', q: str = ''):
    from . import research
    return research.results(sort, limit, level or None, track or None, verdict or None, q)


@app.get('/api/research/summary')
def research_summary():
    from . import research
    return research.summary()


@app.get('/api/backtest')
@perf.ttl_cache(3600)
def backtest_view(t0: str = '2026-09-01'):
    """无未来函数回测：10 个策略轮次。"""
    from . import backtest
    return backtest.run_all(t0)


@app.get('/api/lab/run')
@perf.ttl_cache(1800)
def lab_run(rounds: int = 100, seed: int = 20261007):
    """回测实验室：多期随机事件财报因子回测 + 迭代。"""
    from . import lab
    return lab.run(rounds, seed)


@app.get('/api/backtest/walk')
@perf.ttl_cache(3600)
def backtest_walk(h: int = 5):
    from . import backtest
    return backtest.walkforward(h)


@app.get('/api/peer/{code}')
def peer_view(code: str):
    """赛道对标：公司在财报赛道内的关键指标分位。"""
    from . import research
    return research.peer(code)


@app.get('/api/stocks/search')
def stocks_search(q: str = '', date: str = '20260630', limit: int = 20):
    try:
        return market.search(q, date, limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail='搜索错误: ' + str(e)[:200])


@app.get('/api/metrics')
def metrics():
    return {'uptime_sec': round(time.time() - START_TS, 1), 'version': app.version,
            'cache': ds.cache_stats(), 'watchlist': len(store.list_watch()),
            'alerts': len(store.list_alerts(1000))}


@app.get('/api/suggest/{code}')
def get_suggest(code: str, ttl: int = 6 * 3600):
    r = _wrap(code, ttl)
    return suggest.build(r, with_llm=True)


@app.get('/api/pool/percentile')
def pool_percentile(codes: str = '', ttl: int = 6 * 3600):
    lst = [c.strip() for c in codes.split(',') if c.strip()]
    if not lst:
        lst = [w['code'] for w in store.list_watch()]
    if not lst:
        return {'count': 0, 'metrics': [], 'rows': []}
    return profile.run(lst[:12], ttl)


@app.get('/api/stock/{code}/narrative')
def get_narrative(code: str, ttl: int = 6 * 3600):
    r = _wrap(code, ttl)
    out = llm.narrate(r)
    out['code'] = r['report']['code']
    out['name'] = r['report']['name']
    out['period'] = r['report']['period']
    return out


@app.get('/api/watchlist')
def watchlist():
    return {'items': store.list_watch()}


@app.post('/api/watchlist/{code}')
def watch_add(code: str, name: str = ''):
    return {'items': store.add_watch(code, name)}


@app.delete('/api/watchlist/{code}')
def watch_del(code: str):
    return {'items': store.remove_watch(code)}


@app.get('/api/alerts')
def alerts(limit: int = 100):
    return {'items': store.list_alerts(limit)}


@app.post('/api/alerts/clear')
def alerts_clear():
    store.clear_alerts()
    return {'ok': True}


@app.post('/api/scan')
def do_scan(ttl: int = 3 * 3600):
    return {'results': scanner.scan_once(ttl)}


@app.post('/api/pdf/extract')
async def pdf_upload(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or 'x.pdf')[1] or '.pdf'
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(await file.read())
        return pdf_extract.extract(path)
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


@app.get('/')
def index():
    p = os.path.join(FRONTEND, 'index.html')
    if os.path.exists(p):
        return FileResponse(p)
    return {'ok': True, 'hint': 'frontend not built'}


if os.path.isdir(FRONTEND):
    app.mount('/static', StaticFiles(directory=FRONTEND), name='static')
