# -*- coding: utf-8 -*-
"""QQ 开放平台机器人客户端：鉴权 / 发消息 / 命令路由（财报汇报·问答·预警）。"""
import os, json, time
import requests
try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
except Exception:
    ed25519 = None

DATA_DIR = os.environ.get('FR_DATA_DIR', '/home/ubuntu/fr-agent/data')
CFG = os.path.join(DATA_DIR, 'qqbot.json')
TOKEN_URL = 'https://bots.qq.com/app/getAppAccessToken'
API = 'https://api.sgroup.qq.com'
_AUTH_PREFIX = 'QQ' + 'Bot '

_TOK = {'token': None, 'exp': 0}


def load_cfg():
    try:
        with open(CFG, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'app_id': '', 'client_secret': '', 'app_token': ''}


def save_cfg(d):
    cur = load_cfg()
    cur.update({k: v for k, v in (d or {}).items() if v is not None})
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CFG, 'w', encoding='utf-8') as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CFG, 0o600)
    except Exception:
        pass
    return {'app_id': cur.get('app_id', ''), 'configured': bool(cur.get('app_id') and cur.get('client_secret'))}


def _seed():
    c = load_cfg()
    s = (c.get('bot_secret') or '').strip()
    if not s:
        return None
    try:
        b = bytes.fromhex(s)
        return b if len(b) == 32 else None
    except Exception:
        return None


def sign_validation(plain_token, event_ts):
    """平台回调地址校验握手：signature = Ed25519(event_ts + plain_token)。"""
    seed = _seed()
    if ed25519 is None:
        return {'ok': False, 'error': '缺少 cryptography 依赖'}
    if not seed:
        return {'ok': False, 'error': '未配置 bot_secret（机器人密钥，32 字节 hex）'}
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    msg = (str(event_ts) + str(plain_token)).encode()
    return {'ok': True, 'plain_token': plain_token, 'signature': priv.sign(msg).hex()}


def verify_signature(timestamp, body_bytes, signature_hex):
    """校验平台推送的签名（headers: X-Signature-Ed25519 / X-Signature-Timestamp）。"""
    seed = _seed()
    if ed25519 is None or not seed or not signature_hex or not timestamp:
        return False
    try:
        pub = ed25519.Ed25519PrivateKey.from_private_bytes(seed).public_key()
        pub.verify(bytes.fromhex(signature_hex), str(timestamp).encode() + body_bytes)
        return True
    except Exception:
        return False


def status():
    c = load_cfg()
    ok = bool(c.get('app_id') and c.get('client_secret'))
    out = {'configured': ok, 'app_id': c.get('app_id', ''), 'token_cached': bool(_TOK['token'] and _TOK['exp'] > time.time())}
    if ok:
        t = token()
        out['token_ok'] = bool(t.get('ok'))
        out['token_error'] = t.get('error')
    return out


def token(force=False):
    c = load_cfg()
    if not (c.get('app_id') and c.get('client_secret')):
        return {'ok': False, 'error': '未配置 app_id / client_secret'}
    if not force and _TOK['token'] and _TOK['exp'] > time.time() + 60:
        return {'ok': True, 'access_token': _TOK['token'], 'cached': True}
    try:
        r = requests.post(TOKEN_URL, json={'appId': c['app_id'], 'clientSecret': c['client_secret']}, timeout=12)
        j = r.json()
        if 'access_token' not in j:
            return {'ok': False, 'error': str(j)[:200]}
        _TOK['token'] = j['access_token']
        _TOK['exp'] = time.time() + int(j.get('expires_in', 7200)) - 120
        return {'ok': True, 'access_token': _TOK['token'], 'expires_in': j.get('expires_in')}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200]}


def _headers():
    c = load_cfg()
    t = token()
    if not t.get('ok'):
        return None, t
    return {'Authorization': 'QQBot ' + t['access_token'],
            'X-Union-Appid': str(c.get('app_id', '')),
            'Content-Type': 'application/json'}, None


SEND_PATHS = {
    'group': '/v2/groups/{id}/messages',
    'user': '/v2/users/{id}/messages',
    'channel': '/channels/{id}/messages',
}


def send(target_type, target_id, text, msg_id=None, msg_seq=1):
    path = SEND_PATHS.get(target_type)
    if not path:
        return {'ok': False, 'error': 'target_type 必须是 group/user/channel'}
    h, err = _headers()
    if err:
        return err
    body = {'content': text[:1900], 'msg_type': 0, 'msg_seq': msg_seq}
    if msg_id:
        body['msg_id'] = msg_id
    if target_type == 'channel':
        body.pop('msg_id', None)
        body = {'content': text[:1900], 'msg_id': msg_id}
    try:
        r = requests.post(API + path.format(id=target_id), headers=h, json=body, timeout=15)
        try:
            j = r.json()
        except Exception:
            j = {'raw': r.text[:200]}
        return {'ok': r.status_code < 300, 'status': r.status_code, 'resp': j}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200]}


HELP = ('【财报分析智能体】可用指令：\n'
        '· 财报 600519 —— 生成投研简报\n'
        '· 体检 600519 —— 财报体检（质量分+科目结构）\n'
        '· 风险 600519 —— 风险评分与异常信号\n'
        '· 行情 600519 —— 实时行情\n'
        '· 选股 ROE>15 净利>0 —— 全市场筛选\n'
        '· 预警 —— 查看预警清单\n'
        '· 问 <问题> —— 自由问答（已接入财报数据）')


def handle_command(text, session_key=None, use_agent=True):
    """Agent 优先（自然语言 + 自动调用本机 API），失败回落确定性指令路由。"""
    t = (text or '').strip()
    if not t:
        return HELP
    if use_agent and not t.startswith('/'):
        a = ask_agent(t, session_key)
        if a.get('ok') and (a.get('text') or '').strip():
            return a['text'].strip()[:1900]
        if not t.startswith('/'):
            return ('抱歉，这次没答上来（' + str(a.get('error') or '未知原因')[:120] + '）。'
                    '可重试，或用指令：帮助 / 风险 600519 / 行情 600519 / 财报 600519')
    if t.startswith('/'):
        t = t[1:].strip()
    low = t.lower()
    parts = t.replace('，', ' ').split()
    cmd = parts[0] if parts else ''
    arg = parts[1] if len(parts) > 1 else ''
    from . import brief as brief_mod, checkup, realtime as rt, scanner, store, screener, marketdata, suggest as suggest_mod

    if cmd in ('帮助', 'help', '?', '？'):
        return HELP
    if cmd in ('财报', '简报', 'brief') and arg:
        try:
            r = brief_mod.run(arg)
            return r['markdown'][:1900]
        except Exception as e:
            return '生成失败：' + str(e)[:150]
    if cmd in ('体检', 'checkup') and arg:
        try:
            r = scanner.analyze(arg, 6 * 3600, advanced=False)
            k = checkup.run(r['canonical'], r['indicators'])
            q = k.get('quality') or {}
            lines = ['【财报体检】' + str(r['report']['name']) + '（' + str(k.get('period')) + '）',
                     '质量分：' + str(q.get('score')) + '  评级：' + str(q.get('grade'))]
            for x in (q.get('detail') or []):
                lines.append('· ' + str(x['metric']) + '：' + str(x['value']) + '（得分 ' + str(x['score']) + '）')
            return '\n'.join(lines)[:1900]
        except Exception as e:
            return '体检失败：' + str(e)[:150]
    if cmd in ('风险', 'risk') and arg:
        try:
            r = scanner.analyze(arg, 6 * 3600)
            s = suggest_mod.build(r, with_llm=False)
            return s.get('conclusion_text') or ('【风险评分】' + str(r['report']['name']) + '：' + str((r.get('risk') or {}).get('score')) + '/100')
        except Exception as e:
            return '查询失败：' + str(e)[:150]
    if cmd in ('行情', 'quote') and arg:
        q = rt.quote(arg)
        if not q.get('ok'):
            return '行情不可用：' + str(q.get('error'))
        return (str(q.get('name')) + ' ' + str(q.get('price')) + '  ' + str(q.get('changePct')) + '%\n'
                '开 ' + str(q.get('open')) + ' 高 ' + str(q.get('high')) + ' 低 ' + str(q.get('low')) + '\n'
                'PE ' + str(q.get('pe')) + ' PB ' + str(q.get('pb')) + ' 市值 ' + str(round((q.get('marketCap') or 0) / 1e8, 2)) + '亿')
    if cmd in ('预警', 'alerts'):
        a = store.list_alerts(10)
        if not a:
            return '暂无预警'
        return '【最新预警】\n' + '\n'.join(['· [' + str(x['category']) + '] ' + str(x['code']) + ' ' + str(x['name'] or '') + ' ' + str(x['title']) for x in a[:10]])
    if cmd in ('选股', 'screen'):
        import re
        crit = t[len(cmd):]
        kw = {}
        m = re.search(r'(?:ROE|roe)\s*[>≥]\s*([\d.]+)', crit)
        if m:
            kw['min_roe'] = float(m.group(1))
        m = re.search(r'(?:净利|np)\s*[>≥]\s*([\d.]+)', crit)
        if m:
            kw['min_np_yoy'] = float(m.group(1))
        m = re.search(r'(?:毛利|gm)\s*[>≥]\s*([\d.]+)', crit)
        if m:
            kw['min_gm'] = float(m.group(1))
        r = screener.run(None, kw.get('min_np_yoy'), None, kw.get('min_roe'), kw.get('min_gm'), None, None, ['亏损,净利暴雷'], [], 'score', 8)
        if not r.get('ok'):
            return r.get('reason', '筛选失败')
        return '【选股结果】命中 ' + str(r['matched']) + ' 只，前 8：\n' + '\n'.join(
            ['· ' + x['name'] + '(' + x['code'] + ') 分 ' + str(x['score']) + ' 净利同比 ' + str(x['np_yoy']) + '% ROE ' + str(x['roe']) for x in r['items'][:8]])
    if cmd in ('问', 'ask', 'q'):
        q = t[len(cmd):].strip()
        if not q:
            return '请输入问题，例如：问 600519 的现金流怎么样'
        import re as _re
        code = None
        m = _re.search(r'(\d{6})', q)
        if m:
            code = m.group(1)
        ctx = ''
        if code:
            try:
                r = scanner.analyze(code, 6 * 3600, advanced=False)
                ctx = json.dumps({'report': r['report'], 'indicators': r['indicators']['rows'][:2]}, ensure_ascii=False, default=str)[:3500]
            except Exception:
                pass
        from . import llm
        res = llm.chat([{'role': 'system', 'content': '你是 A 股财报分析助手。只依据给定数据作答，不确定就说数据不足。简体中文，简洁。'},
                        {'role': 'user', 'content': '问题：' + q + ('\n可用数据：' + ctx if ctx else '')}], max_tokens=600)
        return res.get('text') or ('回答失败：' + str(res.get('error')))
    return '未识别指令。\n' + HELP
# -*- coding: utf-8 -*-
"""QQ 机器人 WebSocket 长连接：鉴权握手 / 心跳 / 收 @消息 / 自动回复。"""
import json, threading, time
from concurrent.futures import ThreadPoolExecutor

_WS = {'thread': None, 'running': False, 'state': 'idle', 'error': None,
       'events': 0, 'replies': 0, 'last_event': None, 'last_text': None,
       'started_at': None, 'session_id': None, 'seq': None, 'intents': 1 << 25}


def ws_status():
    s = dict(_WS)
    s.pop('thread', None)
    s['urgent'] = None
    return s


def _gateway_url(token):
    import requests
    r = requests.get('https://api.sgroup.qq.com/gateway',
                     headers={'Authorization': _AUTH_PREFIX + token, 'X-Union-Appid': str(load_cfg().get('app_id', ''))},
                     timeout=15)
    return r.json().get('url')


_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix='qqmsg')


def _dispatch(payload):
    """处理 op0 事件。消息处理丢进线程池，**不阻塞 WS 接收循环**。"""
    t = payload.get('t')
    d = payload.get('d') or {}
    _WS['events'] += 1
    _WS['last_event'] = t
    _WS['last_at'] = time.time()
    if t == 'READY':
        _WS['session_id'] = d.get('session_id')
        _WS['state'] = 'ready'
        return
    if t not in ('GROUP_AT_MESSAGE_CREATE', 'GROUP_MESSAGE_CREATE', 'C2C_MESSAGE_CREATE',
                 'AT_MESSAGE_CREATE', 'DIRECT_MESSAGE_CREATE', 'MESSAGE_CREATE'):
        _WS['last_ignored'] = t
        return
    try:
        _WS['last_payload'] = json.dumps(d, ensure_ascii=False, default=str)[:600]
        _POOL.submit(_handle_msg, d)
        _WS['queued'] = _WS.get('queued', 0) + 1
    except Exception as e:
        _WS['error'] = 'queue: ' + str(e)[:120]


def _handle_msg(d):
    """在 worker 线程里生成并发送回复（agent 可能耗时 20s+，绝不能卡住接收）。"""
    content = (d.get('content') or '').strip()
    _WS['last_text'] = content[:120]
    conv = d.get('group_openid') or (d.get('author') or {}).get('user_openid') or d.get('channel_id') or 'unknown'
    skey = 'agent:main:qq-' + str(conv)[:40]
    try:
        reply = handle_command(content, skey)
    except Exception as e:
        reply = '处理失败：' + str(e)[:120]
    mid = d.get('id')
    gid = d.get('group_openid')
    author = d.get('author') or {}
    uid = author.get('user_openid') or author.get('member_openid') or author.get('id')
    chan = d.get('channel_id')
    try:
        if gid:
            r = send('group', gid, reply, mid)
        elif chan:
            r = send('channel', chan, reply, mid)
        elif uid:
            r = send('user', uid, reply, mid)
        else:
            r = {'ok': False, 'error': 'no target'}
        if r.get('ok'):
            _WS['replies'] += 1
        else:
            _WS['error'] = 'send: ' + json.dumps(r, ensure_ascii=False, default=str)[:160]
    except Exception as e:
        _WS['error'] = 'send exc: ' + str(e)[:160]


def _hb(ws, interval, stop):
    while not stop.is_set():
        stop.wait(interval)
        if stop.is_set():
            break
        try:
            ws.send(json.dumps({'op': 1, 'd': _WS.get('seq')}))
        except Exception:
            return


def _loop():
    from websockets.sync.client import connect
    while _WS['running']:
        try:
            t = token()
            if not t.get('ok'):
                _WS['state'] = 'auth_failed'
                _WS['error'] = str(t.get('error'))[:160]
                time.sleep(15)
                continue
            url = _gateway_url(t['access_token'])
            if not url:
                _WS['state'] = 'no_gateway'
                time.sleep(15)
                continue
            with connect(url, open_timeout=25, close_timeout=5, max_size=2 ** 22) as ws:
                stop = threading.Event()
                hb = None
                for raw in ws:
                    msg = json.loads(raw)
                    op = msg.get('op')
                    if msg.get('s') is not None:
                        _WS['seq'] = msg.get('s')
                    if op == 10:
                        iv = float((msg.get('d') or {}).get('heartbeat_interval', 40000)) / 1000.0
                        if _WS.get('session_id'):
                            ws.send(json.dumps({'op': 6, 'd': {'token': 'QQBot ' + t['access_token'],
                                                               'session_id': _WS['session_id'], 'seq': _WS.get('seq')}}))
                            _WS['state'] = 'resuming'
                        else:
                            ws.send(json.dumps({'op': 2, 'd': {'token': 'QQBot ' + t['access_token'],
                                                               'intents': int(_WS.get('intents', 1 << 25)),
                                                               'shard': [0, 1]}}))
                            _WS['state'] = 'identifying'
                        if hb is None:
                            hb = threading.Thread(target=_hb, args=(ws, max(5.0, iv), stop), daemon=True)
                            hb.start()
                    elif op == 0:
                        _dispatch(msg)
                    elif op == 9:
                        _WS['error'] = 'invalid session'
                        _WS['session_id'] = None
                        break
                    elif op == 7:
                        break
        except Exception as e:
            _WS['error'] = str(e)[:200]
            _WS['state'] = 'error'
        finally:
            try:
                stop.set()
            except Exception:
                pass
        if _WS['running']:
            time.sleep(6)
    _WS['state'] = 'stopped'


def ws_start(intents=None):
    if intents:
        _WS['intents'] = int(intents)
    if _WS['running']:
        return {'ok': True, 'already': True, 'status': ws_status()}
    c = load_cfg()
    if not (c.get('app_id') and c.get('client_secret')):
        return {'ok': False, 'error': '未配置 app_id / client_secret'}
    _WS.update({'running': True, 'state': 'starting', 'error': None, 'started_at': time.time()})
    t = threading.Thread(target=_loop, daemon=True)
    _WS['thread'] = t
    t.start()
    return {'ok': True, 'status': ws_status()}


def ws_stop():
    _WS['running'] = False
    _WS['session_id'] = None
    return {'ok': True, 'status': ws_status()}


# ---------------- Agent 接入（自然语言模式） ----------------
AGENT_PATH = '/home/ubuntu/.local/share/pnpm:/home/ubuntu/.nvm/versions/node/v24.21.0/bin'
AGENT_HOME = '/home/ubuntu'
AGENT_STATS = {'calls': 0, 'ok': 0, 'fail': 0, 'last_ms': None, 'last_error': None}


def _dig(obj, key):
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], str):
            return obj[key]
        for v in obj.values():
            r = _dig(v, key)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _dig(v, key)
            if r:
                return r
    return None


def md2qq(t):
    """把 Markdown 转成 QQ 友好的纯文本（QQ 不渲染 ** / # 等标记）。"""
    import re as _re
    if not t:
        return t
    t = _re.sub(r'\*\*(.+?)\*\*', r'\1', t)
    t = _re.sub(r'(?m)^#{1,6}\s*', '', t)
    t = _re.sub(r'`([^`]+)`', r'\1', t)
    t = _re.sub(r'(?m)^\s*[-*]\s+', '· ', t)
    return t.strip()


def ask_agent(text, session_key=None, timeout=120):
    """把消息交给 fr-agent 自建的 agent 核心（LLM + 工具调用循环），不依赖 OpenClaw。"""
    import time as _t
    from . import agent_core
    t0 = _t.time()
    AGENT_STATS['calls'] += 1
    try:
        r = agent_core.ask(text, session_key)
    except Exception as e:
        AGENT_STATS['fail'] += 1
        AGENT_STATS['last_error'] = str(e)[:160]
        return {'ok': False, 'error': str(e)[:160]}
    AGENT_STATS['last_ms'] = round((_t.time() - t0) * 1000)
    if r.get('ok') and r.get('text'):
        AGENT_STATS['ok'] += 1
        AGENT_STATS['tools_used'] = r.get('tools_used')
        return {'ok': True, 'text': md2qq(r['text']), 'ms': AGENT_STATS['last_ms'],
                'model': r.get('model'), 'tools_used': r.get('tools_used')}
    AGENT_STATS['fail'] += 1
    AGENT_STATS['last_error'] = (r.get('error') or '空输出')[:160]
    return {'ok': False, 'error': (r.get('error') or '空输出')[:160]}


def _dig_out(out):
    import json as _j
    i = out.find('{')
    if i < 0:
        return None
    try:
        j = _j.loads(out[i:out.rfind('}') + 1])
    except Exception:
        j = None
    if j:
        for k in ('finalAssistantVisibleText', 'text'):
            v = _dig(j, k)
            if v:
                return v
    return None


def agent_status():
    return dict(AGENT_STATS)
