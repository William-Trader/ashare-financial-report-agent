# financial-report-claw 📊

> A self-contained, production-grade **A-share financial-report analysis agent** — no external agent framework required. It reads the three financial statements, aligns accounting calibers, flags anomalies, and turns everything into an actionable verdict.

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20Noncommercial-c9a45c.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-3776ab.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-one--command-2496ed.svg)](docker-compose.yml)

**English** · [简体中文](README.zh-CN.md)

---

## Topic

**上市公司财务报告分析 / Financial-report analysis of listed companies.**

This project is specialised for that topic end-to-end: the pipeline, the metrics, the
caliber guards, the anomalies, the deep analysis, the valuation, the classification and the
backtest are all built around **listed-company financial reports** — not trading signals.

Coverage: three-statement extraction · indicator library · cross-footing checks · anomaly &
accounting-caliber detection · report checkup · deep analysis (DuPont / working capital /
cash-flow form / earnings quality / tax / asset quality / scorecard) · red-flag rules ·
forensic scores · DCF + relative valuation · research-report audit · financial-profile tracks ·
report comparison · peer benchmark · multi-factor screener · portfolio risk · roundtable ·
conclusion calibration · cloud whole-market batch analysis · self-contained agent ·
no-look-ahead backtest.

## Why

Financial reports are *edited narratives*. Profit can be book-only; accounting calibers can shift silently. This agent's whole point is to catch that — **cash flow vs. profit divergence** and **accounting-caliber changes** are weighted heaviest. Every number it prints carries a **source + report period** so a human can re-verify.

## Features

| Area | What it does |
|---|---|
| Three-statement extraction | akshare/EastMoney normalized into a uniform schema; PDF upload via pdfplumber |
| Indicator library | gross/net margin, ROE, ROA, debt ratio, cash-to-profit, cash collection, non-recurring share + QoQ/YoY |
| Cross-footing checks | assets = liabilities + equity, cash roll-forward, minority-interest reconciliation, cross-statement net profit |
| Anomaly detection | non-recurring items, caliber/structure shifts, profit–cashflow divergence, goodwill, receivables mismatch |
| Report checkup | one-click health score + risk grade (Watch / Caution / Avoid) |
| Deep analysis | DuPont decomposition + ROE attribution, DSO/DIO/DPO/CCC, cash-flow octants + FCF, earnings quality, tax, asset quality, scorecard |
| Red-flag rules | 10 accounting red flags with level/detail/evidence |
| Forensic scores | Beneish M-Score, Piotroski F-Score, Altman Z-Score, accruals |
| Valuation model | DCF (FCFF) + relative valuation + 5×5 sensitivity matrix + implied range vs. market price |
| Research-report audit | rule layer + LLM layer, line-by-line number/caliber/period/source verification |
| Track classification | whole-market financial-profile tracks: Hyper-growth / Steady-growth / Quality / Cash-cow / Turnaround / Risk |
| Report comparison | 2–6 companies side-by-side + peer percentile within a track |
| Multi-factor screener | cross-sectional z-scores, quintile stratification, composite score |
| Portfolio risk | VaR / CVaR / β / max drawdown / risk contribution / min-variance / risk-parity |
| Conclusion calibration | hit-rate / Brier score over a 5-trading-day horizon |
| **Self-contained agent** | LLM + tool-calling loop (9 financial tools), multi-turn memory — no OpenClaw needed |
| **Cloud batch analysis** | background whole-market pipeline, results persisted, frontend reads cache |
| **No-look-ahead backtest** | multi-period random-event factor backtest + walk-forward |

## Quick Start (Docker — one command)

```bash
git clone https://github.com/<you>/financial-report-claw.git
cd financial-report-claw

# (optional) configure the LLM for the agent / deep reasoning
mkdir -p data
cat > data/.llm.env <<'EOF'
DEEPSEEK_API_KEY=YOUR_KEY_HERE
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_MODEL_DEEP=deepseek-v4-pro
EOF
chmod 600 data/.llm.env
chmod 600 data/.llm.env

docker compose up -d --build

# open http://localhost
curl http://localhost/api/health
```

> The LLM key is optional — data extraction, indicators, checks, anomalies, tracks, screener and the backtest all work without it. The key only enables the natural-language agent, roundtable and deep narrative.

## Quick Start (bare metal)

```bash
bash install.sh          # installs deps + systemd units (Ubuntu/Debian)
systemctl status fr-agent.service
curl http://localhost/api/health
```

## Architecture

```
frontend/index.html     single-file SPA (dark gold theme, self-hosted ECharts, A-share red-up/green-down)
        │ HTTP
        ▼
backend/app/main.py     FastAPI (uvicorn)
        │
   ┌────┼──────────────────────────────────────────────┐
   │ datasource normalize indicators checks anomaly   │  report pipeline
   │ deep forensics bridge crosscheck changepoint     │
   │ valuation_model tracks screener factors          │
   │ portfolio roundtable track trust                 │
   │ agent_core  (LLM + tool-calling loop)            │  self-contained agent
   │ lab / backtest (no-look-ahead)                   │
   │ research (cloud whole-market batch)              │
   └────┼──────────────────────────────────────────────┘
        │
   data/   SQLite warehouse + versioned cache + audit jsonl
        │
   akshare(EastMoney) / Tencent quotes / EastMoney datacenter
```

## Self-contained Agent (no external framework)

`backend/app/agent_core.py` is a full **LLM + tool-calling loop**:

- The model decides which financial tool to call (`analyze`, `deep_analysis`, `quote`, `screen`, `valuation`, `caliber_check`, `events`, `announcements`, …).
- Tools return **pre-computed facts** (not raw text), so the LLM only organizes and judges — hallucination is bounded by design.
- Four-part conclusion: **Verdict / Core judgment / Key evidence / Risks & actions**, each number tagged `[source: field@period]`.

## No-look-ahead Backtest

**Invariant:** the signal only uses information available *at* the decision date T0 (the report period's snapshot, after its legal disclosure deadline); returns only use klines *after* T0. The two never overlap.

- Multi-period walk-forward across 7 report periods (2024Q3 → 2026H1).
- 100-round random-event sampling over {period × horizon × factor × filter × portfolio size}.
- Metrics: excess return vs. equal-weight benchmark, hit-rate, Spearman IC.

## API (selected)

```
GET  /api/health                      health check
GET  /api/stock/{code}/analysis       three statements + indicators + checks + anomalies
GET  /api/checkup/{code}              report checkup
GET  /api/finance/{code}              deep analysis (DuPont / working capital / cash-flow form)
GET  /api/valuation_model/{code}      DCF + relative + sensitivity
GET  /api/tracks                      financial-profile track classification
POST /api/compare                     report comparison (2–6 companies)
GET  /api/peer/{code}                 peer percentile within a track
GET  /api/screener                    multi-factor screener
GET  /api/market/overview             dashboard chart aggregate
POST /api/research/start              cloud whole-market batch analysis
POST /api/agent/ask                   self-contained agent entry
GET  /api/backtest                    no-look-ahead backtest (10 rounds)
GET  /api/lab/run                     100-round random-event backtest lab
```

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `FR_DATA_DIR` | `/home/ubuntu/fr-agent/data` | data directory (SQLite + cache + secrets) |
| `DEEPSEEK_API_KEY` | — | LLM key (optional) |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | LLM endpoint |
| `DEEPSEEK_MODEL` | `deepseek-chat` | fast path |
| `DEEPSEEK_MODEL_DEEP` | `deepseek-v4-pro` | reasoning path |

## Documentation

| Doc | Content |
|---|---|
| docs/ARCHITECTURE.md | Architecture & module map |
| docs/ENGINEERING.md | Invariants & self-healing |
| docs/DEPLOY.md | Deploy (systemd / nginx / Docker) |
| docs/data-sources.md | Data sources, rate limits, calibers |
| docs/qq-bot.md | QQ bot integration |
| ../08_回测结果/ | Validation results (9 XLSX + 13-chapter report) |

## Disclaimer

Research use only. **Not investment advice.** Data comes from public endpoints and may be delayed or incomplete; every conclusion carries its source and report period. Use at your own risk.

## License

**PolyForm Noncommercial License 1.0.0** — free for **noncommercial** use only (personal study, research, education, hobby projects, nonprofit/government use). **Commercial use, resale, or any profit-making use is NOT permitted** without a separate commercial license from the author. See [LICENSE](LICENSE).

Required Notice: Copyright (c) 2026 William-Trader (https://github.com/William-Trader)

