# QQ 机器人（qq-bot）

## 一、形态
- 机器人走 QQ 官方开放平台 **WebSocket 长连接**（wss://api.sgroup.qq.com/websocket），无需公网回调。
- 前端「QQ 机器人」页可配置 AppID / AppSecret / bot_secret（写入 data/qqbot.json，600 权限），并查看连接状态。

## 二、命令路由
| 用户说 | 动作 |
|---|---|
| 代码/公司名 | 跑分析并回四段式结论 |
| 「风险 600519」 | 风险与红旗摘要 |
| 其它自然语言 | 交给自持 Agent（agent_core.ask，同一 session_key 多轮记忆）|

## 三、工程要点（血泪）
1. **消息处理必须投线程池**：一条 ~20s 的 agent 回复若内联在 WS 接收循环里，会堵住其余会话。
2. **QQ 不渲染 Markdown**：回复必须经 qqbot.md2qq() 去掉 ** / # / 反引号并把列表转成纯文本，否则用户看到满屏星号。
3. **凭据只落 600 权限文件**，不在日志/回复/代码里回显；缺凭据时如实报 configured:false，绝不假装成功。
4. **回调验签**：若用 Webhook 形态，需校验签名；本作品默认 WebSocket 形态。

## 四、端点
- POST /api/qq/config（配置）· GET /api/qq/status · POST /api/qq/ws/start|stop · GET /api/qq/ws/status
- POST /api/qq/command（离线试跑命令）· POST /api/qq/agent/test（离线试跑 Agent）
