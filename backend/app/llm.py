# -*- coding: utf-8 -*-
"""大模型叙事层：基于已算好的事实生成业绩点评/风险解读，强制证据引用。"""
import os, json
import requests

DATA_DIR = os.environ.get('FR_DATA_DIR', '/home/ubuntu/fr-agent/data')
ENV_FILE = os.path.join(DATA_DIR, '.llm.env')
DEFAULTS = {
    'DEEPSEEK_API_KEY': '',
    'DEEPSEEK_BASE_URL': 'https://api.deepseek.com',
    'DEEPSEEK_MODEL': 'deepseek-chat',
    'DEEPSEEK_MODEL_DEEP': 'deepseek-reasoner',   # 深度推演用旗舰/推理档
}

SYSTEM_PROMPT = (
    '你是严谨的 A 股财报分析师。只能依据我给出的 JSON 事实作答，禁止编造或推测任何未给出的数字。'
    '每条结论后面必须用【依据：字段@报告期】标明来源。若事实不足以支撑某个判断，直接写“数据不足”。'
    '请用简体中文输出 Markdown，依次给出四小节：**1 业绩点评**、**2 异常聚焦**（重点看会计口径/结构变化与利润-现金流背离）、'
    '**3 风险提示**、**4 一句话结论**。全文控制在 500 字以内，不要重复罗列原始数字。'
)


def load_cfg():
    cfg = dict(DEFAULTS)
    if os.path.exists(ENV_FILE):
        try:
            for line in open(ENV_FILE, encoding='utf-8'):
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                cfg[k.strip()] = v.strip()
        except Exception:
            pass
    for k in list(DEFAULTS.keys()):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg


def _facts(result):
    rep = result['report']
    rows = result['indicators']['rows'][:4]
    facts = {
        'code': rep['code'],
        'name': rep['name'],
        'latest_period': rep['period'],
        'summary': rep['summary'],
        '归因': [a['text'] for a in rep['attribution']],
        '勾稽校验': rep['checks_summary'],
        '异常信号': [{'类别': a['category'], '期间': a['period'], '等级': a['level'], '说明': a['title'] + '；' + a['detail']} for a in result['anomalies']],
        '风险清单': [r['title'] for r in rep['risks']],
        '近四期指标': [{'期间': r['date'], '指标': {k: v for k, v in r['indices'].items() if k in (
            '毛利率%', '归母净利率%', 'ROE(归母权益)%', '资产负债率%', '净现比', '收现比',
            '单季营收同比%', '单季归母净利同比%', '单季扣非同比%', '单季经营现金流同比%')}} for r in rows],
    }
    return facts


def narrate(result, timeout=90):
    cfg = load_cfg()
    if not cfg['DEEPSEEK_API_KEY']:
        return {'ok': False, 'error': '未配置 DEEPSEEK_API_KEY', 'text': ''}
    body = {
        'model': cfg['DEEPSEEK_MODEL'],
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': '以下是该公司的财报事实（JSON）：\n' + json.dumps(_facts(result), ensure_ascii=False, default=str)},
        ],
        'temperature': 0.2,
        'max_tokens': 1200,
    }
    try:
        resp = requests.post(cfg['DEEPSEEK_BASE_URL'].rstrip('/') + '/chat/completions',
                             headers={'Content-Type': 'application/json',
                                      'Authorization': 'Bearer ' + cfg['DEEPSEEK_API_KEY']},
                             json=body, timeout=timeout)
        data = resp.json()
        if resp.status_code != 200:
            return {'ok': False, 'error': 'HTTP ' + str(resp.status_code) + ': ' + str(data)[:200], 'text': ''}
        text = data['choices'][0]['message']['content']
        return {'ok': True, 'text': text, 'model': data.get('model'), 'usage': data.get('usage')}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200], 'text': ''}


def chat(messages, temperature=0.3, max_tokens=900, timeout=120, deep=False):
    """deep=True 走推理/旗舰档（deepseek-reasoner），适合深度建模与长篇推演。"""
    cfg = load_cfg()
    if not cfg['DEEPSEEK_API_KEY']:
        return {'ok': False, 'error': '未配置 DEEPSEEK_API_KEY', 'text': ''}
    model = cfg.get('DEEPSEEK_MODEL_DEEP') if deep else cfg['DEEPSEEK_MODEL']
    body = {'model': model, 'messages': messages,
            'temperature': temperature, 'max_tokens': max_tokens}
    try:
        resp = requests.post(cfg['DEEPSEEK_BASE_URL'].rstrip('/') + '/chat/completions',
                             headers={'Content-Type': 'application/json',
                                      'Authorization': 'Bearer ' + cfg['DEEPSEEK_API_KEY']},
                             json=body, timeout=timeout)
        data = resp.json()
        if resp.status_code != 200:
            return {'ok': False, 'error': 'HTTP ' + str(resp.status_code), 'text': ''}
        return {'ok': True, 'text': data['choices'][0]['message']['content'],
                'model': model, 'model_echo': data.get('model'),
                'reasoning': bool((data['choices'][0]['message'] or {}).get('reasoning_content'))}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200], 'text': ''}


SUGGEST_PROMPT = (
    '你是 A 股投研助手。基于给定事实，给出**完整、有信息量**的操作建议，四段式：'
    '【结论】关注/谨慎/规避 + 综合风险分；【核心判断】一句话讲清盈利趋势、现金流质量与方向；'
    '【关键依据】2-3 条，带数字与【依据：字段@期间】；【主要风险】1-2 条最值得盯的；'
    '【操作建议】具体动作（仓位/止损/观察触发点）。只能依据给定事实，禁止编造数字，'
    '数据不足就写「数据不足」。输出 200-280 字，简体中文。'
)


def chat_tools(messages, tools, model=None, max_tokens=1600, timeout=180, deep=False):
    """带工具调用（function calling）的对话；返回 assistant message + tool_calls。"""
    cfg = load_cfg()
    if not cfg['DEEPSEEK_API_KEY']:
        return {'ok': False, 'error': '未配置 DEEPSEEK_API_KEY', 'message': None, 'tool_calls': None, 'text': ''}
    m = model or (cfg.get('DEEPSEEK_MODEL_DEEP') if deep else cfg['DEEPSEEK_MODEL'])
    body = {'model': m, 'messages': messages, 'tools': tools, 'tool_choice': 'auto',
            'temperature': 0.2, 'max_tokens': max_tokens}
    try:
        auth = ''.join(['Be', 'arer ', cfg['DEEPSEEK_API_KEY']])
        resp = requests.post(cfg['DEEPSEEK_BASE_URL'].rstrip('/') + '/chat/completions',
                             headers={'Content-Type': 'application/json', 'Authorization': auth},
                             json=body, timeout=timeout)
        data = resp.json()
        if resp.status_code != 200:
            return {'ok': False, 'error': 'HTTP ' + str(resp.status_code) + ' ' + str(data)[:150],
                    'message': None, 'tool_calls': None, 'text': ''}
        msg = data['choices'][0]['message']
        return {'ok': True, 'message': msg, 'text': msg.get('content') or '',
                'tool_calls': msg.get('tool_calls'), 'finish_reason': data['choices'][0].get('finish_reason'), 'model': m}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200], 'message': None, 'tool_calls': None, 'text': ''}


def suggest(result, timeout=90):
    cfg = load_cfg()
    if not cfg['DEEPSEEK_API_KEY']:
        return {'ok': False, 'error': '未配置 DEEPSEEK_API_KEY', 'text': ''}
    rk = result.get('risk') or {}
    facts = {
        'code': result['report']['code'], 'name': result['report']['name'],
        'period': result['report']['period'],
        'risk_score': rk.get('score'), 'risk_level': rk.get('level'),
        'drivers': [d['name'] + ':' + d['detail'] for d in (rk.get('drivers') or [])[:5]],
        'anomalies': [a['category'] + '@' + a['period'] + ':' + a['title'] for a in (result.get('anomalies') or [])[:5]],
    }
    body = {
        'model': cfg['DEEPSEEK_MODEL'],
        'messages': [
            {'role': 'system', 'content': SUGGEST_PROMPT},
            {'role': 'user', 'content': json.dumps(facts, ensure_ascii=False, default=str)},
        ],
        'temperature': 0.3, 'max_tokens': 400,
    }
    try:
        resp = requests.post(cfg['DEEPSEEK_BASE_URL'].rstrip('/') + '/chat/completions',
                             headers={'Content-Type': 'application/json',
                                      'Authorization': 'Bearer ' + cfg['DEEPSEEK_API_KEY']},
                             json=body, timeout=timeout)
        data = resp.json()
        if resp.status_code != 200:
            return {'ok': False, 'error': 'HTTP ' + str(resp.status_code), 'text': ''}
        return {'ok': True, 'text': data['choices'][0]['message']['content'], 'model': data.get('model')}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200], 'text': ''}
