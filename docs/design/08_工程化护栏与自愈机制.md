# 工程化护栏与自动修复机制

> 本文件记录 financial-report-claw 的**可靠性铁律**与**自愈机制**。任何新增外部数据源都必须遵守。

## 一、为什么需要（事故复盘）

**事故**：2026-10-07，前端「加载不出来」。

**根因链**：密集拉取 8 个报告期快照 + 启动 K 线同步 → 触发上游（东方财富）限流 → `ak.stock_yjbb_em(...)` **抓取永久挂起（无超时）** → `market.snapshot()` 不返回 → `market.digest()` 卡死 → `/api/market/overview` 与 `/api/bootstrap` 一起卡 30s+ → 总览页取不到数据。

**教训**：**一个被限流的接口，可以把整站拖死。** 外部调用的不可靠性必须被工程化地隔离。

## 二、铁律（Invariants）

1. **任何网络抓取都必须有超时** —— 统一走 `app/safe.py: with_timeout(fn, timeout=8, default)`，绝不裸调 `requests.get(...)` / `akshare.*`。
2. **超时/失败必须降级可用** —— 回退到本地 SQLite 仓库或内存缓存，返回「上一次已知良好」的数据，绝不把异常直接抛给前端。
3. **市场级摘要不依赖实时抓取** —— 总览/首屏的市场摘要走 `_wh_digest()`（本地仓库构建，~0.02s），实时抓取只用于增量刷新。
4. **每一次超时/回退都要留痕** —— 写 `data/guard.log` 并计数，`GET /api/reliability` 可观测。
5. **重计算接口必须预热** —— 启动时按「先轻后重」顺序预热（总览/首屏 → 赛道 → 回测），首访即命中缓存。
6. **重后台任务限流且可断点续跑** —— 1 worker + 间隔，意图标志持久化，绝不饿死站点。

## 三、护栏机制

### 1) 超时隔离（safe.with_timeout）

```python
from app import safe
df = safe.with_timeout(lambda: cached(key, ttl, fetch), 8, None, 'snapshot:20260630')
if df is None:
    # 降级：用本地仓库
    ...
```

在守护线程里执行，超时立即返回 `default`；被抛弃的线程最终完成时会写入缓存（**stale-while-revalidate**）。

### 2) 本地兜底（warehouse-backed）

- `main._wh_digest()`：从 `warehouse.market_snap()` 构建 `{date, stats, board, top, text}`，**不碰 akshare**。
- `market.snapshot()/digest()`：akshare 超时后不再无限等待，返回 `available:false` 或退回仓库快照。

### 3) 观测（guard.log + /api/reliability）

- `data/guard.log`：`时间 类型 标签`（TIMEOUT / FALLBACK）。
- `GET /api/reliability`：返回 `{timeouts, fallbacks, incidents[], boot}`。

### 4) 启动预热（先轻后重）

```python
# main.py 启动钩子
market_overview()      # 1. 总览（最重要，先热）
tracks.run('')         # 2. 赛道
backtest.run_all()     # 3. 回测（最重，最后）
```

## 四、自愈流程

1. 外部抓取超时 → `with_timeout` 立即返回兜底值（页面不卡）。
2. 页面拿到的是「本地仓库 / 上次缓存」的数据（**降级但可用**，带 `source` 标注）。
3. 后台线程继续尝试真实抓取，成功则回写缓存（下次即新数据）。
4. 事件写入 `guard.log`；运维可通过 `/api/reliability` 发现异常源并针对性限流/换源。

## 五、运维检查清单

- `GET /api/health` → `{ok:true}`
- `GET /api/reliability` → `timeouts/fallbacks` 不应持续增长
- `systemctl is-active fr-agent.service` → active
- `uptime` → load 应低于核数（2 核机 < 2.0）
- 站点 `ttfb` < 0.3s

