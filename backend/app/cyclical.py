# -*- coding: utf-8 -*-
"""周期股财报专项：量价拆分 / 科目穿透 / 异常三级定性 / 情景压力测试。

针对周期股（有色/黄金/煤炭/钢铁/石油/化工/建材等重资产行业）财报分析最核心、也最易
「只能定性、不能定量」的四处硬功夫。原则：能定量就定量，缺数据就诚实标注。
"""
import datetime as _dt
from . import scanner

CYCLICAL_KW = ('有色', '黄金', '煤炭', '钢铁', '石油', '化工', '建材', '采矿', '能源',
               '燃气', '铜', '铝', '锂', '稀土', '贵金属', '基础化工', '油气')
NAME_KW = ('矿', '煤', '钢', '油', '有色', '黄金', '铜', '铝', '锂', '稀土', '化工',
           '建材', '燃气', '能源', '电力', '硅', '钛', '钼', '钨', '铅', '锌')


def is_cyclical(industry, name=None):
    ind = industry or ''
    nm = name or ''
    if any(k in ind for k in CYCLICAL_KW):
        return True
    if any(k in nm for k in NAME_KW):
        return True
    return False


TRIAGE = [
    ('危险', ('减值', '商誉', '存贷双高', '利息收入与货币资金背离', '资金占用', '违规担保',
              '经营现金流为负', '净利润与现金流背离', '非标', '立案', '造假', '虚增', '应收增速远超',
              '存货增速远超', '扣非为负', '非经常性损益占比', '质押率')),
    ('需核实', ('会计口径', '口径', '结构变化', '重述', '追溯', '关联', '汇兑', '套保', '公允价值',
               '毛利率同比变动', '毛利率变动', '费用率', '审计意见')),
    ('可解释', ('行业', '周期', '季节', '矿业', '采矿权', '探矿权', '商品价格', '涨价', '并购',
               '扩张', '资本开支', '在建工程', '产量', '产能')),
]


def triage_level(text):
    t = text or ''
    for level, kws in TRIAGE:
        if any(k in t for k in kws):
            return level
    return '需核实'


def triage(anomalies, checks):
    """异常/勾稽逐项三级定性 + 去重。勾稽类 fail 多为四舍五入/汇兑/少数股东 → 可解释。"""
    seen = {}
    for a in (anomalies or []):
        title = a.get('title') or a.get('detail') or a.get('category') or ''
        if not title:
            continue
        lv = triage_level(title + (a.get('category') or '') + (a.get('detail') or ''))
        if '勾稽' in title:
            lv = '可解释'
        seen.setdefault(title, {'level': lv, 'periods': []})['periods'].append(a.get('period') or '')
    for ck in (checks or []):
        if isinstance(ck, dict) and ck.get('status') == 'fail':
            name = ck.get('name') or '勾稽校验失败'
            seen.setdefault(name, {'level': '可解释', 'periods': []})['periods'].append(ck.get('period') or '')
    items = [{'title': t, 'level': v['level'], 'periods': len(v['periods']),
              'period_sample': (v['periods'][0] if v['periods'] else '')} for t, v in seen.items()]
    items.sort(key=lambda x: ({'危险': 0, '需核实': 1, '可解释': 2}[x['level']], x['title']))
    n = {'危险': 0, '需核实': 0, '可解释': 0}
    for it in items:
        n[it['level']] += 1
    return {'items': items, 'counts': n,
            'note': '三级定性：危险=减值/资金/现金流/造假类；需核实=口径/结构/关联/汇兑；可解释=行业/周期/商品价格/严格勾稽四舍五入。'}


def stress_test(indices, commodity_share=0.6, shocks=(-10, -20, -30)):
    def g(k):
        v = indices.get(k)
        return v if isinstance(v, (int, float)) else None
    gm = g('毛利率%')
    npm = g('归母净利率%')
    if gm is None or npm is None or abs(npm) < 0.1:
        return {'ok': False, 'reason': '缺少毛利率/归母净利率，无法做情景测算'}
    rows = []
    for s in shocks:
        rev_delta = s * commodity_share
        profit_delta = rev_delta * 100.0 / npm
        rows.append({'shock_pct': s, 'revenue_pct': round(rev_delta, 1), 'net_profit_pct': round(profit_delta, 1)})
    return {'ok': True, 'gross_margin': round(gm, 2), 'net_margin': round(npm, 2),
            'commodity_share': commodity_share, 'leverage': round(100.0 / npm, 1),
            'assumption': '假设量短期不变、成本结构不变、商品价变动全额传导到营收；净利变动≈价格变动×商品占比×100/归母净利率。商品收入占比为输入参数（默认 0.6）。',
            'rows': rows}


def price_volume_split(report, indices, price_yoy=None):
    attrs = {a.get('item'): a.get('yoy_pct') for a in (report.get('attribution') or []) if a.get('yoy_pct') is not None}
    rev_g = attrs.get('营业总收入') or attrs.get('营业收入')
    np_g = attrs.get('归母净利润') or attrs.get('净利润')
    gm_now = indices.get('毛利率%')
    out = {'ok': True, 'rev_growth_pct': rev_g, 'np_growth_pct': np_g,
           'gross_margin_now': round(gm_now, 2) if gm_now is not None else None}
    if rev_g is None or np_g is None:
        return {'ok': False, 'reason': '缺营收/净利同比，无法拆分'}
    if price_yoy is not None:
        price = price_yoy
        vol = ((1 + rev_g / 100.0) / (1 + price / 100.0) - 1) * 100.0
        out['price_driven_pct'] = round(price, 1)
        out['volume_driven_pct'] = round(vol, 1)
        out['price_yoy'] = price
    else:
        out['price_volume_note'] = '未提供商品价格同比；见 segment_split（已接入主营构成+商品期货价）做按品种拆分。'
    margin_and_other = (np_g or 0) - (rev_g or 0)
    out['margin_and_other_pp'] = round(margin_and_other, 1)
    out['note'] = ('净利增速 ≈ 营收增速(量×价) + 毛利率提升/费用/汇兑/套保/一次性(残差 %.1fpp)。价驱动不可持续，量驱动可持续。' % margin_and_other)
    return out


def goodwill_intangibles(indices):
    def g(k):
        v = indices.get(k)
        return v if isinstance(v, (int, float)) else None
    gw = g('商誉占归母权益%')
    out = {'ok': True, 'goodwill_pct_equity': round(gw, 2) if gw is not None else None}
    if gw is not None:
        out['goodwill_flag'] = '高' if gw > 20 else ('中' if gw > 10 else '低')
    out['intangible_note'] = ('重资产的「无形资产」主体通常是采矿权/探矿权而非商誉。需穿透：采矿权/探矿权/商誉各占多少、是否做过减值测试、'
                              '按当前商品价测算的可回收价值。明细在财报附注，可用 /api/notes/{code} 抽取（担保/质押/关联/减值）。')
    out['impairment_flag'] = ('若商品价大幅下跌，高溢价并购形成的商誉/矿权存在减值风险；'
                              '触发点=可回收金额<账面价值，需逐矿权减值测试，而非行业通用免死金牌。')
    return out


COMMODITY_SEG = {
    '黄金': ('金锭', '金精矿', '矿产金', '矿山产金', '合质金', '黄金', '金矿'),
    '铜': ('铜精矿', '矿产铜', '矿山产铜', '阴极铜', '电积铜', '电解铜', '产铜'),
    '锌': ('锌锭', '锌精矿', '矿产锌', '矿山产锌', '产锌'),
    '银': ('银锭', '银精矿', '矿产银', '矿山产银', '产银'),
    '锂': ('碳酸锂', '锂精矿', '锂盐', '氢氧化锂'),
}
COMMODITY_SYM = {'黄金': 'AU0', '铜': 'CU0', '锌': 'ZN0', '银': 'AG0'}
_SEG_CACHE = {}


def _f(v):
    try:
        x = float(v)
        return x if x == x else None
    except Exception:
        return None


def _ak_symbol(code):
    c = (code or '').strip().zfill(6)
    return ('SH' if c[0] == '6' else 'SZ') + c


def _price_yoy(sym):
    try:
        import akshare as ak
        df = ak.futures_zh_daily_sina(symbol=sym)
        df['date'] = df['date'].astype(str)
        last = df.iloc[-1]
        d0 = (_dt.datetime.strptime(last['date'], '%Y-%m-%d') - _dt.timedelta(days=365)).strftime('%Y-%m-%d')
        base = df[df['date'] <= d0]
        if not len(base):
            return None
        b = base.iloc[-1]
        return {'date': last['date'], 'close': _f(last['close']),
                'yoy_pct': round((_f(last['close']) / _f(b['close']) - 1) * 100, 1)}
    except Exception:
        return None


def _segments(code):
    key = 'seg:' + _ak_symbol(code)
    now = _dt.datetime.now().timestamp()
    c = _SEG_CACHE.get(key)
    if c and c[0] > now:
        return c[1]
    try:
        import akshare as ak
        df = ak.stock_zygc_em(symbol=_ak_symbol(code))
    except Exception:
        return None
    df = df[df['分类类型'] == '按产品分类']
    dates = sorted(set(df['报告日期'].astype(str)))
    if not dates:
        return None

    def rows_of(d):
        out = {}
        for _, r in df[df['报告日期'].astype(str) == d].iterrows():
            rev = _f(r['主营收入'])
            if rev is not None and rev > 0:
                out[str(r['主营构成'])] = rev
        return out
    latest = dates[-1]
    y = int(latest[:4])
    mmdd = latest[4:]
    prev = [d for d in dates if d[4:] == mmdd and d[:4] == str(y - 1)]
    res = {'latest': latest, 'prev': (prev[-1] if prev else None),
           'latest_rows': rows_of(latest), 'prev_rows': rows_of(prev[-1]) if prev else {}}
    _SEG_CACHE[key] = (now + 6 * 3600, res)
    return res


def segment_split(code):
    """量价拆分闭环：主营构成按产品 + 商品价格同比 → 价驱动 / 量驱动。"""
    seg = _segments(code)
    if not seg:
        return {'ok': False, 'reason': '主营构成不可用（akshare stock_zygc_em）'}
    lr, pr = seg['latest_rows'], seg['prev_rows']
    total = sum(lr.values())
    out = []
    for comm, kws in COMMODITY_SEG.items():
        rn = sum(v for k, v in lr.items() if any(kw in k for kw in kws))
        rp = sum(v for k, v in pr.items() if any(kw in k for kw in kws))
        if rn <= 0:
            continue
        rev_g = ((rn / rp - 1) * 100) if rp > 0 else None
        px = _price_yoy(COMMODITY_SYM[comm]) if comm in COMMODITY_SYM else None
        vol_g = None
        if rev_g is not None and px and px.get('yoy_pct') is not None:
            vol_g = ((1 + rev_g / 100.0) / (1 + px['yoy_pct'] / 100.0) - 1) * 100
        out.append({'commodity': comm, 'revenue_now': rn, 'share_pct': round(rn / total * 100, 1) if total else None,
                    'revenue_growth_pct': round(rev_g, 1) if rev_g is not None else None,
                    'price_yoy_pct': (px or {}).get('yoy_pct'), 'volume_growth_pct': round(vol_g, 1) if vol_g is not None else None,
                    'price_date': (px or {}).get('date')})
    out.sort(key=lambda x: -(x['revenue_now'] or 0))
    return {'ok': True, 'report_period': seg['latest'], 'compare_period': seg['prev'], 'total_revenue': total,
            'segments': out,
            'note': '量价拆分：某商品营收增速 = 价(商品期货价同比) × 量(产量同比，由 收入/价格 反推)。价驱动不可持续、量驱动可持续。'}


def run(code, price_yoy=None, commodity_share=0.6):
    code = (code or '').strip()
    try:
        r = scanner.analyze(code, 6 * 3600, advanced=True, periods=8)
    except Exception as e:
        return {'ok': False, 'reason': '分析失败: ' + str(e)[:120]}
    rep = r.get('report') or {}
    ind = (r.get('indicators') or {}).get('rows') or []
    indices = ind[0].get('indices') if ind and ind[0].get('indices') else {}
    industry = rep.get('industry') or ''
    if not industry:
        try:
            from . import marketdata
            pf = marketdata.profile(code) or {}
            industry = pf.get('industry') or ''
        except Exception:
            industry = ''
    cyclical = is_cyclical(industry, rep.get('name'))
    return {
        'ok': True, 'code': code, 'name': rep.get('name'), 'period': rep.get('period'),
        'industry': industry, 'cyclical': cyclical,
        'triage': triage(r.get('anomalies'), r.get('checks')),
        'stress_test': stress_test(indices, commodity_share=commodity_share),
        'price_volume_split': price_volume_split(rep, indices, price_yoy=price_yoy),
        'segment_split': segment_split(code),
        'chain_position': chain_position(code),
        'goodwill_intangibles': goodwill_intangibles(indices),
        'risk': r.get('risk'),
        'note': '周期股时序纪律：deep_analysis 必须与 analyze 同轮调齐、先交叉再下结论（见 agent_core）。',
    }


CHAIN_STAGE = {
    '上游(资源/采矿)': ('矿', '采', '资源', '原料', '勘探', '选矿', '精矿', '矿石', '油气', '煤层'),
    '中游(冶炼/加工)': ('冶炼', '精炼', '加工', '材料', '合金', '铸', '中间品', '阴极', '电积', '化工', '发酵'),
    '下游(制造/终端)': ('制造', '设备', '终端', '消费', '品牌', '整车', '电池', '组件', '器件', '系统', '整机'),
    '流通(贸易/销售)': ('贸易', '销售', '物流', '分销', '商贸', '零售'),
}


def chain_position(code):
    """产业链位置（启发式）：按主营构成产品名关键词归类：上游/中游/下游/流通。"""
    seg = _segments(code)
    if not seg:
        return {'ok': False, 'reason': '主营构成不可用（akshare）'}
    lr = seg['latest_rows']
    total = sum(lr.values()) or 1
    agg = {}
    for name, rev in lr.items():
        stage = '其他/未分类'
        for st, kws in CHAIN_STAGE.items():
            if any(k in name for k in kws):
                stage = st
                break
        agg[stage] = agg.get(stage, 0) + rev
    rows = [{'stage': k, 'revenue': v, 'share_pct': round(v / total * 100, 1)} for k, v in agg.items()]
    rows.sort(key=lambda x: -x['revenue'])
    return {'ok': True, 'report_period': seg['latest'], 'stages': rows,
            'position': (rows[0]['stage'] if rows else None),
            'note': '产业链位置：按主营构成产品名关键词启发式归类（上游=资源/采矿、中游=冶炼/加工、下游=制造/终端、流通=贸易）。这是「公司处于链条哪一环」的启发式，不是供应链上下游映射。'}
