# -*- coding: utf-8 -*-
"""三表规范化：东方财富三大报表 -> 统一字段（中文名 + 数值），按报告期倒序。"""
from concurrent.futures import ThreadPoolExecutor
from .datasource import balance_sheet, profit_sheet, cash_flow, to_em_symbol, stock_name

BS_FIELDS = [
    ('TOTAL_ASSETS', '总资产'),
    ('TOTAL_LIABILITIES', '总负债'),
    ('TOTAL_EQUITY', '所有者权益合计'),
    ('MINORITY_EQUITY', '少数股东权益'),
    ('TOTAL_CURRENT_ASSETS', '流动资产合计'),
    ('TOTAL_CURRENT_LIAB', '流动负债合计'),
    ('TOTAL_NONCURRENT_ASSETS', '非流动资产合计'),
    ('TOTAL_NONCURRENT_LIAB', '非流动负债合计'),
    ('MONETARYFUNDS', '货币资金'),
    ('ACCOUNTS_RECE', '应收账款'),
    ('NOTE_ACCOUNTS_RECE', '应收票据及应收账款'),
    ('PREPAYMENT', '预付款项'),
    ('INVENTORY', '存货'),
    ('FIXED_ASSET', '固定资产'),
    ('INTANGIBLE_ASSET', '无形资产'),
    ('GOODWILL', '商誉'),
    ('SHORT_LOAN', '短期借款'),
    ('LONG_LOAN', '长期借款'),
    ('ACCOUNTS_PAYABLE', '应付账款'),
    ('NOTE_ACCOUNTS_PAYABLE', '应付票据及应付账款'),
    ('CONTRACT_LIAB', '合同负债'),
    ('TAX_PAYABLE', '应交税费'),
    ('SHARE_CAPITAL', '股本'),
    ('CAPITAL_RESERVE', '资本公积'),
    ('SURPLUS_RESERVE', '盈余公积'),
    ('OTHER_COMPRE_INCOME', '其他综合收益'),
    ('TOTAL_PARENT_EQUITY', '归母权益合计'),
]

IS_FIELDS = [
    ('TOTAL_OPERATE_INCOME', '营业总收入'),
    ('OPERATE_INCOME', '营业收入'),
    ('OPERATE_COST', '营业成本'),
    ('TOTAL_OPERATE_COST', '营业总成本'),
    ('SALE_EXPENSE', '销售费用'),
    ('MANAGE_EXPENSE', '管理费用'),
    ('RESEARCH_EXPENSE', '研发费用'),
    ('ME_RESEARCH_EXPENSE', '研发费用(合并)'),
    ('FINANCE_EXPENSE', '财务费用'),
    ('FE_INTEREST_EXPENSE', '利息费用'),
    ('FE_INTEREST_INCOME', '利息收入'),
    ('OPERATE_PROFIT', '营业利润'),
    ('TOTAL_PROFIT', '利润总额'),
    ('INCOME_TAX', '所得税费用'),
    ('NETPROFIT', '净利润'),
    ('PARENT_NETPROFIT', '归母净利润'),
    ('MINORITY_INTEREST', '少数股东损益'),
    ('DEDUCT_PARENT_NETPROFIT', '扣非归母净利润'),
    ('BASIC_EPS', '基本每股收益'),
]

CF_FIELDS = [
    ('NETCASH_OPERATE', '经营活动现金流净额'),
    ('NETCASH_INVEST', '投资活动现金流净额'),
    ('NETCASH_FINANCE', '筹资活动现金流净额'),
    ('SALES_SERVICES', '销售商品提供劳务收到的现金'),
    ('BUY_SERVICES', '购买商品接受劳务支付的现金'),
    ('PAY_STAFF_CASH', '支付给职工以及为职工支付的现金'),
    ('PAY_ALL_TAX', '支付的各项税费'),
    ('FA_IR_DEPR', '固定资产折旧等'),
    ('IA_AMORTIZE', '无形资产摊销'),
    ('LPE_AMORTIZE', '长期待摊费用摊销'),
    ('USERIGHT_ASSET_AMORTIZE', '使用权资产摊销'),
    ('BEGIN_CASH_EQUIVALENTS', '期初现金及现金等价物'),
    ('END_CASH_EQUIVALENTS', '期末现金及现金等价物'),
    ('NETPROFIT', '净利润(现金流补充)'),
]


def _num(v):
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:
            return None
        return f
    except Exception:
        return None


def build_statement(df, fields):
    out = []
    for row in df or []:
        date = str(row.get('REPORT_DATE', ''))[:10]
        if not date:
            continue
        item = {
            'date': date,
            'type': row.get('REPORT_TYPE', ''),
            'name': row.get('REPORT_DATE_NAME', ''),
        }
        vals = {}
        for col, label in fields:
            if col in row:
                vals[label] = _num(row.get(col))
        item['values'] = vals
        out.append(item)
    out.sort(key=lambda x: x['date'], reverse=True)
    return out


def canonical(code, ttl=6 * 3600):
    """并行取三表+名称（原来 4 次串行网络请求 → 并行，显著加速批量灌数）。"""
    sym = to_em_symbol(code)
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_bs = ex.submit(balance_sheet, code, ttl)
        f_is = ex.submit(profit_sheet, code, ttl)
        f_cf = ex.submit(cash_flow, code, ttl)
        f_nm = ex.submit(stock_name, code)
        try:
            bs = build_statement(f_bs.result(), BS_FIELDS)
        except Exception:
            bs = []
        try:
            is_ = build_statement(f_is.result(), IS_FIELDS)
        except Exception:
            is_ = []
        try:
            cf = build_statement(f_cf.result(), CF_FIELDS)
        except Exception:
            cf = []
        try:
            nm = f_nm.result()
        except Exception:
            nm = ''
    return {'code': sym, 'name': nm, '资产负债表': bs, '利润表': is_, '现金流量表': cf}


def period_of(item):
    return item.get('date', '')


def find_period(stmt, date):
    for it in stmt:
        if it['date'] == date:
            return it
    return None


def annual_or_latest(stmt):
    for it in stmt:
        if it['date'][5:7] == '12':
            return it
    return stmt[0] if stmt else None


def prev_year_date(date):
    y, m = date[:4], date[5:7]
    return str(int(y) - 1) + '-' + m + '-' + date[8:10]
