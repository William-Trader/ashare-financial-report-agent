# GitHub 上架文案包 · financial-report-claw

> 直接复制粘贴。按 GitHub 表单字段排列。

## 1) Repository name

```
financial-report-claw
```

## 2) Description（≤350 字符，英文，填 About 的 Description）

```
Self-contained A-share financial-report analysis agent: three-statement pipeline, cross-footing checks, accounting-caliber & profit-cashflow divergence detection, DuPont deep analysis, DCF valuation, research-report audit, report tracks, multi-factor screener, and a no-look-ahead multi-period backtest lab. FastAPI + single-file SPA, Docker one-command deploy.
```

## 2b) Description（中文备选）

```
独立自持的 A 股财报分析智能体：三表加工、勾稽校验、会计口径与利润-现金流背离识别、杜邦深析、DCF 估值、研报纠错、财报赛道分类、多因子选股，以及无未来函数的多报告期回测实验室。FastAPI + 单文件 SPA，Docker 一键部署。
```

## 3) Website（About 的 Website 字段）

```
http://<your-host>/
```

## 4) Topics（贴进去逐个回车，最多 20 个）

```
finance
fintech
quant
quantitative-finance
financial-analysis
financial-statements
a-share
china-stock-market
valuation
dcf
backtesting
fastapi
python
llm
llm-agent
ai-agent
tool-calling
deepseek
dashboard
docker
```

## 5) Social preview / 一句话简介

```
财报不是数字，是被修饰过的叙述。financial-report-claw 专门盯利润与现金流的背离、以及悄悄变化的会计口径 —— 并把全市场 5000+ 家公司的财报统一分析。
```

## 6) Release v1.0 notes（GitHub Releases 正文）

```markdown
## financial-report-claw v1.0

First public release.

### Highlights
- **Self-contained agent** — a real LLM tool-calling loop (14 financial tools), multi-turn memory, no external agent framework.
- **Report pipeline** — three-statement extraction, indicator library, cross-footing checks, anomaly detection (accounting caliber + profit/cashflow divergence).
- **Deep analysis** — DuPont decomposition & ROE attribution, DSO/DIO/DPO/CCC, cash-flow octants + FCF, earnings quality, tax, asset quality, scorecard, 10 red-flag rules, forensic scores (Beneish/Piotroski/Altman).
- **Valuation** — DCF(FCFF) + relative valuation + 5x5 sensitivity matrix.
- **Research-report audit** — rule layer + LLM layer.
- **Whole-market** — financial-profile tracks, 2-6 company comparison, peer percentile, multi-factor screener, portfolio risk (VaR/CVaR/beta/drawdown).
- **Cloud batch analysis** — background whole-market pipeline with persisted results.
- **No-look-ahead backtest lab** — multi-period walk-forward + 100-round random-event factor backtest.
- **Frontend** — single-file SPA, dark-gold theme, self-hosted ECharts, A-share red-up/green-down, 7-chart market dashboard.
- **Deploy** — Docker one-command (`docker compose up -d --build`).

### Notes
- Data: akshare / EastMoney / Tencent. Public endpoints only.
- LLM key optional — everything except the natural-language agent works offline.
- Research use only. Not investment advice.
```

## 7) 首发推广贴（可发 X / 知乎 / 掘金 / V2EX）

```
📊 开源了一个 A 股财报分析智能体 financial-report-claw。

它不是又一个「问财报」的聊天框 —— 它盯的是财报里最会骗人的两件事：
① 利润涨、现金流不涨（利润含金量）
② 悄悄变的会计口径

能力：三表加工 → 勾稽校验 → 异常识别 → 杜邦深析 → DCF 估值 → 研报纠错 → 财报赛道分类 → 多因子选股，外加一个「无未来函数」的多报告期回测实验室（100 轮随机事件因子回测）。

技术：FastAPI + 单文件 SPA + 自持 LLM 工具调用 Agent（不依赖任何外部 agent 框架）+ 本地 SQLite 仓库。Docker 一键起站。

每个结论都带【依据：字段@期间】，可回源、可审计。

地址：http://<your-host>/   代码：<repo url>
仅供研究，不构成投资建议。
```

## 8) 上架命令（你晚上执行）

```bash
cd <cloned-repo>
git remote add origin git@github.com:<你的账号>/financial-report-claw.git
git push -u origin main
```

推完在 GitHub 网页：About 填 §2 的 Description + §3 的 Website + §4 的 Topics；Releases 建 v1.0 粘 §6；发帖用 §7。

