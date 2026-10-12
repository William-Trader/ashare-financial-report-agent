# -*- coding: utf-8 -*-
"""活跃策略（选股综合分权重）。

诚实说明：全样本复核（K 线换新浪源补到 4871 只、每期约 4900 只、7 期全有效 n=7）：
- 原 v3 优化权重 h=5/10/20 = -1.32% / -2.64% / -1.88%，样本外为负；
- 等权四因子 +0.57%（胜率 71%）反优于 v3 —— 权重优化是负贡献；
- 单因子最好为净利率 +1.31%、ROE +0.86%；随机权重 -0.14%。
据此回退为等权四因子，并保留「未通过验证」标注。
"""
ACTIVE = {
    'name': '综合分（等权四因子）· 未通过大样本验证',
    'weights': {'np_yoy': 0.25, 'rev_yoy': 0.25, 'roe': 0.25, 'gm': 0.25},
    'horizon_days': 5,
    'topn': 8,
    'filter': '非暴雷',
    'validation': {
        'method': '全样本（每组约 4900 只 · 7 期全有效 n=7）',
        'equal_weight_excess_pct': 0.57,
        'equal_weight_win_pct': 71.0,
        'equal_weight_t': 0.70,
        'v3_optimized_excess_pct': -1.32,
        'v3_optimized_note': '权重优化为负贡献（-1.32% vs 等权 +0.57%）',
        'best_single': '净利率 +1.31% / ROE +0.86%',
        'random_weight_pct': -0.14,
        'verdict': '因子策略未通过全样本样本外检验；已回退等权以减害。',
    },
}


def weights():
    return dict(ACTIVE['weights'])


def info():
    return dict(ACTIVE)
