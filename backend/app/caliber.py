# -*- coding: utf-8 -*-
"""口径守卫：显式声明每个结论用的口径，并对边界情形（金融股 / 中期未年化 / 单季不可推算 / 同比基准缺失 / 单位）告警。"""
from .normalize import find_period

DAYS = {'03': 90, '06': 181, '09': 273, '12': 365}
FIN_KW = ('银行', '保险', '证券', '信托', '金融')


def _g(stmt, d):
    it = find_period(stmt, d)
    return it['values'] if it else {}


def _n(v):
    return v if isinstance(v, (int, float)) else None


def run(canon, ind=None, industry=''):
    bs, is_, cf = canon['资产负债表'], canon['利润表'], canon['现金流量表']
    isd = sorted([x['date'] for x in is_], reverse=True)
    if not isd:
        return {'ok': False, 'reason': '无报告期'}
    d = isd[0]
    mm = d[5:7]
    days = DAYS.get(mm, 365)
    is_mid = mm != '12'
    i = _g(is_, d)
    items = []
    warn = []

    # 1) 期间口径：累计 vs 单季
    items.append({'项': '利润表/现金流量表', '口径': '年初至今累计（YTD）', '期间': d,
                  '说明': 'EM 三表为累计口径；单季 = 本期累计 − 同年前一报告期累计'})

    # 2) 中期未年化
    if is_mid:
        warn.append({'等级': '中', '项': '年化口径', '说明': '当前为中期报告（%s），ROE/增长率等为**累计未年化**，不可与年报直接横比' % d,
                     '依据': '报告期 %s 非 12 月' % d})

    # 3) 单季可推算性
    same_year_prev = [x for x in isd if x < d and x[:4] == d[:4]]
    if is_mid and not same_year_prev:
        warn.append({'等级': '中', '项': '单季推算', '说明': '缺少同年前一报告期，单季值无法推算（会退化为累计值）', '依据': '缺 %s 年内的更早报告期' % d[:4]})
    items.append({'项': '单季值', '口径': '单季 = 累计 − 同年前期累计', '期间': d,
                  '可用': bool(same_year_prev),
                  '说明': '可推算' if same_year_prev else '不可推算（缺同年前期）'})

    # 4) 同比基准
    y = _g(is_, str(int(d[:4]) - 1) + d[4:])
    has_yoy = bool(y)
    if not has_yoy:
        warn.append({'等级': '中', '项': '同比基准', '说明': '上年同期缺失，同比不可用（不得用上一报告期代替）', '依据': '缺 %s' % (str(int(d[:4]) - 1) + d[4:])})
    items.append({'项': '同比', '口径': '上年同期（period_date[:4]-1 + 同月日）', '期间': d,
                  '可用': has_yoy, '说明': '基准存在' if has_yoy else '基准缺失'})

    # 5) 金融股特例
    has_rev = _n(i.get('营业总收入')) is not None
    has_cost = _n(i.get('营业成本')) is not None
    fin = any(k in (industry or '') for k in FIN_KW)
    if fin or not has_rev or not has_cost:
        warn.append({'等级': '高', '项': '金融股/特殊科目', '说明': '无营业总收入或营业成本 → 毛利率/费用率/周转类指标**不可计算**，须返回 N/A 而非 0（行业：%s）' % (industry or '未知'),
                     '依据': '营业总收入=%s / 营业成本=%s' % ('有' if has_rev else '缺', '有' if has_cost else '缺')})
    items.append({'项': '毛利率类', '口径': '依赖营业总收入/营业成本', '可用': bool(has_rev and has_cost),
                  '说明': '可计算' if (has_rev and has_cost) else '金融股特例：不适用'})

    # 6) 平均值口径
    y0 = [x for x in sorted([it['date'] for it in bs], reverse=True) if x < d and x[5:7] == '12']
    has_base = bool(y0)
    items.append({'项': '周转率/ROE 分母', '口径': '平均余额 = (期末 + 上年末)/2', '期间': d,
                  '可用': has_base, '说明': '有基期' if has_base else '缺上年末 → 退化为期末余额（口径变弱）'})
    if not has_base:
        warn.append({'等级': '低', '项': '平均余额', '说明': '缺上年末数据，周转/ROE 退化为期末口径，可比性下降'})

    # 7) 单位
    items.append({'项': '数值单位', '口径': '原始人民币元；展示层换算亿/万', '期间': d, '说明': '不做四舍五入后再计算'})

    # 8) 现金流量表出现净利润双源
    cf_np = _n(_g(cf, d).get('净利润(现金流补充)'))
    is_np = _n(i.get('净利润'))
    dual = None
    if cf_np is not None and is_np is not None and is_np:
        dual = abs(cf_np - is_np) / abs(is_np) * 100
        if dual > 1:
            warn.append({'等级': '中', '项': '净利润双源不一致', '说明': '利润表净利润与现金流量表补充资料净利润差异 %.2f%%，需核对口径' % dual,
                         '依据': '利润表 %.0f / 现金流量表补充 %.0f' % (is_np, cf_np)})

    order = {'高': 0, '中': 1, '低': 2}
    warn.sort(key=lambda x: order.get(x['等级'], 3))
    return {'ok': True, 'period': d, 'is_interim': is_mid, 'days_in_period': days,
            'declarations': items, 'warnings': warn,
            'boundary_risk': ('高' if any(w['等级'] == '高' for w in warn) else ('中' if any(w['等级'] == '中' for w in warn) else '低')),
            'note': '口径守卫只做“声明与告警”，不改数；任何结论都应带上这里声明的口径'}
