# 部署（DEPLOY）

## 一、一键部署
    bash install.sh                 # 本机/服务器均可
    # 或容器化：
    docker compose up -d --build

## 二、运行形态（生产）
- 服务：systemd 单元 fr-agent.service，uvicorn 直接监听 0.0.0.0:80（同时服务 SPA 与 API）
- 定时：fr-agent-scan.timer 每日扫描自选并生成预警
- 目录：/home/ubuntu/fr-agent/{backend,frontend,venv,data}
- 数据：data/warehouse.sqlite3（仓库）、data/cache/cache.sqlite3（缓存）、data/.llm.env（600）、data/qqbot.json（600）

## 三、环境变量
| 变量 | 说明 |
|---|---|
| FR_DATA_DIR | 数据目录（默认 ./data）|
| DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL | LLM（写入 data/.llm.env，600 权限）|
| DEEPSEEK_MODEL / DEEPSEEK_MODEL_DEEP | 快档 / 深档模型 |

## 四、健康检查
    curl http://localhost/api/health      # {"ok":true}
    curl http://localhost/api/about       # 版本与选题
    curl http://localhost/api/reliability # 超时/兜底计数
    systemctl is-active fr-agent.service

## 五、注意事项
- 安全组仅放开 22 与 80；SPA 与 API 都走 80。
- 重后台任务（全量回补）必须限流并断点续跑，且安排在夜间，避免拖垮 2 核站点。
- 数据源有 WAF/限流（见 data-sources.md），回补需限速 + 冷却。
