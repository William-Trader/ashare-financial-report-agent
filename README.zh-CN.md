# financial-report-claw · 财报分析智能体

> 独立自持的 A 股财报分析智能体。**不依赖任何外部 agent 框架**——自带 LLM 工具调用引擎，把三表吃透、把口径对齐、把异常挑出来、把结论落到可执行的建议上。

一个能上架 GitHub 的独立作品：FastAPI 后端 + 单文件 SPA 前端 + 自持 Agent 核心 + 本地 SQLite 数据仓库。

## 它是什么

把 A 股财报从原始三表加工成可执行投研结论的完整流水线。核心立场：

- **先给数字，再给判断**：每个结论都带【依据：字段@期间】，可回源、可审计。
- **怀疑精神**：财报是被修饰过的叙述，利润涨而现金流不涨、口径悄悄变、非经常性撑起盈利——这些是它盯的重点。
- **口径优先**：会计口径变化与利润-现金流背离的权重最高。

## 核心能力

| 模块 | 说明 |
|---|---|
| 三表提取 | akshare(东方财富) 规范化为统一字段；支持上传财报 PDF 用 pdfplumber 解析 |
| 指标库 | 毛利率/净利率/ROE/ROA/资产负债率/净现比/收现比/扣非占比 + 单季同比环比 |
| 勾稽校验 | 资产=负债+权益、现金期初期末勾稽、归母+少数=净利润、表间净利润一致 等 |
| 异常识别 | 非经常性损益、口径/结构突变、利润与现金流背离、商誉占比、应收错配 |
| 财报体检 | 一键体检报告 + 风险评分（关注/谨慎/规避） |
| 财报深析 | 杜邦分解、周转与现金周期、现金流形态、盈利质量、税负、资产质量、评分卡 |
| 红旗库 | 财务红旗规则库（多期背离、口径变化、激进确认等） |
| 法证评分 | Beneish / Piotroski / Altman / 应计质量 |
| 估值建模 | DCF(FCFF) + 相对估值 + 5×5 敏感性矩阵 + 区间 + 市价对比 |
| 研报纠错 | 规则层 + LLM 层逐条核验数值/口径/期间/来源/逻辑 |
| 全市场选股 | 多因子打分 + 因子分层 + 财报赛道分类 |
| 组合风控 | VaR / CVaR / β / 最大回撤 / 风险贡献 / 最小方差 / 风险平价 |
| 结论校准 | 命中率 / Brier 分数，5 交易日 horizon 复盘 |
| 证据链 | 审计 jsonl + 合规元数据 + 幻觉拦截 |

## 自持 Agent 引擎（不依赖 OpenClaw）

backend/app/agent_core.py 是一个完整的 LLM + 工具调用循环：

- 大模型（DeepSeek）自行决定调用哪个财报工具（analyze / deep_analysis / quote / screen / valuation / caliber_check / events / announcements …）
- 工具返回**已算好的事实**（不是原始文本），LLM 只做组织与判断，防幻觉
- 每轮输出四段式结论：【结论】【核心判断】【关键依据】【操作建议】，每条带【依据：字段@期间】

## 前端（玄金终端）

单文件 SPA（哈希路由，自托管 ECharts），A 股红涨绿跌：

- **财报赛道分类**：全市场按财报画像自动分层（爆发增长 / 稳健成长 / 质量白马 / 现金奶牛 / 困境反转 / 风险规避）
- **财报对比**：2-6 只标的并排（核心指标 / 同比 / 风险分 / 估值 / 勾稽）
- 全市场异动、个股多页签分析、选股、因子分层、组合风控、圆桌研判、持仓、估值、研报纠错
- 表头排序 / 分页 / CSV 导出 / 骨架屏 / 快捷键

## 架构

    frontend/index.html  单文件 SPA（玄金终端）
            │ HTTP (80)
            ▼
    backend/app/main.py  FastAPI（uvicorn，公网 80）
            │
       ┌────┼─────────────────────────────────────┐
       │ scanner  normalize  indicators  checks   │  财报加工层
       │ anomaly  deep  forensics  bridge  crosscheck │
       │ valuation  portfolio  roundtable  track  │
       │ tracks  screener  factors  attribution   │
       │ agent_core（LLM + 工具调用循环）          │  自持 Agent
       │ qqbot（QQ 机器人 WebSocket 长连接）        │
       └────┼─────────────────────────────────────┘
            │
       data/  SQLite 数据仓库 + 缓存 + 审计 jsonl
            │
       akshare(东财) / 腾讯行情 / 东财 datacenter

数据源：akshare + 东方财富 push2/datacenter/F10 + 腾讯行情；全市场用业绩预告接口 + A 股白名单过滤。

## 快速开始

    # 1. 安装依赖
    bash install.sh

    # 2. 配置 LLM 凭据（可选，用于 agent 与圆桌/深析的推理档）
    cat > data/.llm.env <<'EOF'
    DEEPSEEK_API_KEY=sk-xxx
    DEEPSEEK_BASE_URL=https://api.deepseek.com
    DEEPSEEK_MODEL=deepseek-chat
    DEEPSEEK_MODEL_DEEP=deepseek-chat
    EOF
    chmod 600 data/.llm.env

    # 3. 启动
    sudo systemctl start fr-agent.service

    # 4. 验证
    curl http://localhost/api/health
    curl http://localhost/api/tracks

> 凭据文件 data/.llm.env 权限 600，密钥不进代码、不进日志、不进版本库。

## 主要 API

    GET  /api/health                      健康检查
    GET  /api/stock/{code}/analysis       个股分析（三表+指标+勾稽+异常）
    GET  /api/stock/{code}/advanced       深度分析（风险+红旗+现金流桥）
    GET  /api/checkup/{code}              财报体检
    GET  /api/finance/{code}              财报深析（杜邦/周转/现金流形态）
    GET  /api/valuation_model/{code}      估值建模（DCF+相对+敏感性）
    GET  /api/tracks                      财报赛道分类（全市场）
    POST /api/compare                     财报对比（2-6 只并排）
    GET  /api/screener                    全市场多因子选股
    GET  /api/market/digest               全市场异动摘要
    POST /api/portfolio/risk              组合风控
    GET  /api/roundtable/{code}           五角色圆桌研判
    POST /api/report_check                研报纠错
    POST /api/agent/ask                   自持 Agent 对话入口（LLM+工具）
    GET  /api/warehouse/stats             数据仓库状态

## 文档

| 文档 | 内容 |
|---|---|
| docs/ARCHITECTURE.md | 架构与模块地图 |
| docs/ENGINEERING.md | 工程铁律与自愈机制 |
| docs/DEPLOY.md | 部署（systemd / nginx / Docker）|
| docs/data-sources.md | 数据源、限流与口径 |
| docs/qq-bot.md | QQ 机器人接入 |
| docs/GITHUB_META.md | 上架元信息（描述/topics）|
| ../04_功能设计详解/ | 11 份功能设计文档（含 09 效力验证与盲测）|
| ../08_回测结果/ | 效力验证成果（九份 XLSX + 13 章评估报告）|

## 合规声明

本项目输出仅供研究参考，**不构成投资建议**。数据来自公开接口，可能存在延迟或缺失；所有结论均标注数据来源与报告期。最终决策由使用者自负其责。

## License

**PolyForm Noncommercial License 1.0.0** —— 仅限**非商业用途**（个人学习、研究、教育、爱好项目、非营利/政府用途）。**未经作者单独授权，禁止任何商业化、盈利性使用或转售**。详见 [LICENSE](LICENSE)。

Required Notice: Copyright (c) 2026 William-Trader (https://github.com/William-Trader)

## 选题方向

**上市公司财务报告分析。**

本作品**围绕该选题端到端特化**：从数据管线、指标口径、异常识别、深析、估值、赛道分层到回测，
全部服务于**上市公司财务报告**本身，而非交易信号。
