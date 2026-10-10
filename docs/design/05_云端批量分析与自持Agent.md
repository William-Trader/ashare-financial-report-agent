# 云端全市场批量分析 + 自持 Agent

## 云端批量分析（research.py）
- 后台逐股跑确定性流水线（scanner.analyze advanced）→ 压缩研究记录落 research 表
- 端点：start / stop / status / results / summary / peer
- 前端只读缓存结果，无需实时渲染
- 限流：1 worker + 0.2s 间隔；断点续跑（已分析跳过）；结果跨重启保留
- 优先分析异动幅度大的（按 |净利同比| 降序）

## 自持 Agent（agent_core.py，不依赖 OpenClaw）
- LLM + 工具函数调用循环；**14 个工具**：analyze / deep_analysis / quote / market_overview / screen / announcements / caliber_check / valuation / events / peer_benchmark / checkup / thesis / dividend / fundflow
- 工具返回「已算好的事实」，LLM 只做组织与判断（防幻觉）
- 四段式结论：【结论】【核心判断】【关键依据】【操作建议】，关键数字带【依据：字段@期间】
- 双档路由：简单取数走快路径，需判断走深档（deepseek-v4-pro）；**用 has_reasoning 判定档位，不信任回显 model 字段**
- 多轮记忆：按 session_key 保留最近 6 轮
- 此前 ask_agent 通过 subprocess 调 OpenClaw CLI，现已完全自持

## 效力验证（eval_lab.py / optimize.py / backtest.py / lab.py）
- /api/eval：横截面分层（数百轮 + 五档/IC）+ 预测量效 + 造假案例验证
- /api/optimize：训练期优化 + 留出期验证（walk-forward）
- /api/backtest：无未来函数十轮；/api/lab/run：100 轮随机事件
- 产物与诚实结论见 [09_效力验证与盲测.md](09_效力验证与盲测.md)
