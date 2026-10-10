# 架构文档 · financial-report-claw

## 设计原则

1. **能自算就自算**：杜邦、周转、现金流形态、红旗、风险分全部从三表计算，外部只取原始数据，减少对单一数据源的依赖。
2. **口径优先**：会计口径变化、利润-现金流背离权重最高；金融股无营业总收入/成本时相关比率返回 N/A 而非 0；中期 ROE 为累计未年化；同比必须比去年同期。
3. **数据不显旧**：报告期自动探测；行情/指数/资金流带来源与时间戳；批量数据带 as_of。
4. **可用性即尊重**：重后台任务不进服务主进程（ThreadPoolExecutor 并发 + 定时器独立进程）；SQLite 版本化缓存；前端 stale-while-revalidate。
5. **自持 Agent**：LLM 只吃已算好的事实，工具循环自主决策，不依赖外部 agent 框架。

## 模块地图（backend/app/）

| 文件 | 职责 |
|---|---|
| main.py | FastAPI 路由聚合，静态前端托管 |
| agent_core.py | 自持 Agent 引擎：LLM + 工具函数调用循环 |
| llm.py | DeepSeek 客户端（chat + chat_tools + 推理档降级） |
| datasource.py | akshare 三表拉取 + 缓存 |
| normalize.py | 字段规范化（累计/单季、金融股特例） |
| indicators.py | 指标库 + 单季同比环比 |
| checks.py | 勾稽校验 |
| anomaly.py | 异常识别（口径/背离/商誉/应收） |
| report.py | 结构化报告 + 归因 + 证据链 |
| scanner.py | 单股扫描 + 全市场并发扫描 |
| deep.py | 财报深析（杜邦/周转/现金流形态/评分卡/红旗） |
| forensics.py | 法证评分（Beneish/Piotroski/Altman/应计） |
| bridge.py | 利润→现金流桥 |
| crosscheck.py | 表间交叉校验 |
| valuation_model.py | 估值建模（DCF+相对+敏感性） |
| tracks.py | 财报赛道分类 + 财报对比 |
| screener.py | 全市场多因子选股 |
| portfolio.py | 组合风控（VaR/CVaR/β/回撤/风险贡献） |
| roundtable.py | 五角色圆桌研判 |
| track.py | 结论校准（命中率/Brier） |
| trust.py | 证据链 + 审计 jsonl + 幻觉拦截 |
| market.py / realtime.py | 市场异动 / 实时行情（腾讯） |
| warehouse.py | 本地 SQLite 数据仓库 |
| qqbot.py | QQ 机器人（WebSocket 长连接 + 回调 + 命令路由） |
| store.py | SQLite 连接池（显式 close，防锁） |

## 数据流

    akshare/东财/腾讯
       │  (datasource + realtime + marketdata)
       ▼
    本地 SQLite 仓库 + 版本化缓存（store.py / warehouse.py）
       │
       ▼
    加工层（normalize → indicators → checks → anomaly → deep/forensics/bridge）
       │
       ▼
    结论层（scanner → report → suggest → trust）
       │
       ▼
    API（main.py） ──► 前端 SPA / agent_core / qqbot

## 已知硬坑

- SQLite：with sqlite3.connect() as c: 只提交不关闭 → 连接泄漏 → database is locked；不可在写事务里再开连接（自死锁）。
- 单文件前端被截断时「提取 script + node --check」会误报 OK；必须先验文件完整（收尾标签、体积、符号数）。
- 全市场行数 ≠ 全市场：业绩快照含新三板，需 A 股白名单过滤。
- 重后台任务不得与服务同进程抢资源。
