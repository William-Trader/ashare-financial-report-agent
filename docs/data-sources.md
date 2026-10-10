# 数据源与获取（data-sources）

## 一、数据源
| 用途 | 来源 | 说明 |
|---|---|---|
| 三表 / 指标 / 摘要 | akshare（东方财富）| stock_*_by_report_em |
| 行情 / 指数 / 资金流 | 腾讯 | qt.gtimg.cn / ifzq.gtimg.cn |
| K 线（前复权日线）| 腾讯 fqkline | param=<code>,day,,,<n>,qfq |
| 行业 / 公司档案 | 东财 F10 | CompanySurvey（EM2016）|
| 事件（龙虎榜/两融/大宗/预告）| 东财 datacenter | 单源失败仅标注 ok:false |

## 二、铁律
1. **任何网络抓取必须有超时**：统一走 app/safe.py: with_timeout(fn, 8, default)，绝不裸调 requests / akshare。
2. **超时/失败必须降级**：回退本地 SQLite 仓库或上次缓存，返回带 source 标注的数据。
3. **市场级摘要走本地仓库**（_wh_digest，~0.02s），实抓仅用于增量刷新。
4. **每次超时/回退留痕**：data/guard.log + GET /api/reliability 可观测。
5. **缓存键版本化**：改数据结构要换 key 前缀（如 mkt→mkt2），否则旧缓存让修复「看起来没生效」。

## 三、限流与封禁（实测）
- **腾讯 fqkline 有 WAF**：突发批量返回 HTTP 501 + JS 挑战页（waf.tencent），服务器 IP 会被临时封禁；单请求正常。
- **东财 push2his 按 IP 限流**：Python requests/urllib 可能被直接拒（RemoteDisconnected），curl 可通；两个 IP 大量请求后都会被限。
- **回补策略**：限速（并发 ≤2 + 间隔）+ 冷却；被封后等 10–60 分钟再小批量重试。
- **内存安全**：K 线到数百万行后须**逐代码流式**导出（ORDER BY code 逐个 flush），不可整体载入。

## 四、口径
- 东财三表是「年初至今累计」：单季 = 本期累计 − 同年前一报告期累计；Q1 即单季。
- 同比基准 = 去年同期（年份 -1），否则会把同比算成环比。
- 金融股无营业总收入/成本 → 相关比率 N/A（永不填 0）。
