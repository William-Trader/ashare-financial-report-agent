# -*- coding: utf-8 -*-
"""活跃策略（选股综合分权重）。

诚实说明：本策略的权重来自小样本优化；在把 K 线历史扩到约 3 年、每期样本升到约 2580 只后，
样本外超额由 +3.54%(3 折) 变为 -2.37%(4 期) —— 原正超额是小样本假象，策略未通过大样本检验。
因此本站将其定位为「可复现的评估框架 + 综合分排序」，而非可声称 alpha 的策略。
细节见参赛 08_回测结果/H_扩样后效力复核.xlsx 与评估报告第十二章。
"""
ACTIVE = {
    'name': '综合分 v3（成长+质量）· 未通过大样本验证',
    'weights': {'np_yoy': 0.0, 'rev_yoy': 0.4957, 'roe': 0.2644, 'gm': 0.2399},
    'horizon_days': 5,
    'topn': 8,
    'filter': '非暴雷',
    'validation': {
        'method': '留一法交叉验证（每折重拟合）',
        'folds_attempted': 7,
        'folds_effective': 3,
        'cv_excess_pct': 3.54,
        'cv_win_pct': 100.0,
        'cv_t': 1.63,
        'cv_significant': False,
        'note_small_sample': '仅 3 折样本充足；t=1.63 未达显著。',
        'expanded_sample': {
            'sample': '每期约 2580 只 · 共 69,743 行 · K 线历史约 3 年',
            'excess_pct': -2.37,
            'effective_periods': 4,
            'win_pct': 25.0,
            'verdict': '未通过样本外检验；原 +3.54% 为小样本假象',
        },
        'benchmark_note': '单因子最好为营收 +0.56%；唯一正向为规模（小市值 +1.38%，属已知风格 beta）。',
        'positioning': '作品定位为「严谨可复现的评估框架 + 带误报率的风险预筛选」，不声称策略 alpha。',
    },
}


def weights():
    return dict(ACTIVE['weights'])


def info():
    return dict(ACTIVE)
