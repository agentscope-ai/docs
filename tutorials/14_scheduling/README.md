# Tutorial 14: Schedule — 定时任务与自动化

> **什么时候需要这个？** Agent 要按时间表自动跑——每天早上生成销售日报、每小时巡检、每周出分析报告——而不是等用户输入。无人值守场景下你还要处理"权限确认怎么办"和"要不要保留历史上下文"两个关键问题。

## 本章基于前序章节

- **T07 — `PermissionMode.DONT_ASK`**：无人值守时把 ASK 自动转为 DENY，必须靠 Allow 规则提前授权。
- **T10 — Context 压缩**：Stateful 定时任务会持续累积上下文，必须配套压缩策略。
- **T13 — `create_app()` / Session / DataMuse 工具**：本章的 `/schedule` 路由跑在 T13 启动的 Agent Service 上，并复用服务端注入的 `SalesProfile` / `SalesBreakdown`。

## 你将学到

- Schedule API 的使用方式
- Cron 表达式驱动的定时任务
- Stateful vs Stateless 模式
- 定时任务的权限模式
- 定时任务触发后如何查看 Session 和运行状态
- Cron 创建前校验、Workspace 绑定与多副本 owner
- 通过 API 管理定时任务

## 前置要求

- 完成 Tutorial 13
- Agent Service 正常运行
- `pip install -e ".[service,storage-sql]" aiosqlite httpx`

## 核心概念

### 定时任务的价值

Agent 不只是等待用户输入——它可以按时间表自动执行任务：

- 每天早上生成销售日报
- 每小时检查系统健康状况
- 每周生成分析报告
- 定时清理临时文件

### Schedule API

定时任务通过 Agent Service 的 `/schedule` 路由管理，也可以由 Agent 自己通过 `ScheduleCreate` 工具创建。当前服务端会把 schedule 的 `description` 作为触发时发送给 Agent 的任务输入，所以这里建议写成可直接执行的任务描述。

```
POST   /schedule        ── 创建定时任务
GET    /schedule        ── 列出所有定时任务
GET    /schedule/{id}/sessions ── 查看任务触发的会话
DELETE /schedule/{id}   ── 删除定时任务
```

Schedule 只负责"按时间触发 Agent"；触发后真正执行的是一个 Session。要看运行状态或事件流，继续使用 T13 的 Session API：

```
GET /sessions/{session_id}/status?agent_id=...
GET /sessions/{session_id}/stream?agent_id=...
GET /sessions/{session_id}/messages?agent_id=...
```

服务端会先校验 cron 的 5 个字段、IANA timezone 和生效窗口，全部通过后才写入
Storage；非法请求返回 422，不会留下无法触发的记录。本章代码会先发送一次故意
错误的 cron，验证这条行为。

每次计划触发时，Scheduler 会通过 `WorkspaceManager` 为自动创建的 Session 分配
真实 `workspace_id`。因此 T13 注入的工具、MCP、Skill 和文件隔离规则同样适用于
后台任务，而不是在一个没有 Workspace 的特殊执行路径里运行。

### 多副本部署

APScheduler 的 timer 在进程内运行。如果多个 API 副本都使用默认
`enable_scheduler=True`，同一个任务会在每个副本各触发一次。部署时只让一个
进程持有 timer：

```python
# scheduler owner
app = create_app(..., enable_scheduler=True)

# 其余 API replicas
app = create_app(..., enable_scheduler=False)
```

关闭 timer 不会关闭 `/schedule` API；其他副本仍能保存任务，并通过 MessageBus
通知 owner 更新调度状态。

### 创建定时任务

```bash
curl -X POST http://localhost:8000/schedule \
  -H "X-User-Id: demo-user" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "<agent-id>",
    "name": "Daily Sales Report",
    "description": "Use SalesProfile and SalesBreakdown by category, then generate a 5-bullet sales summary.",
    "cron_expression": "0 9 * * *",
    "timezone": "Asia/Shanghai",
    "chat_model_config": {
      "type": "dashscope_chat",
      "credential_id": "<credential-id>",
      "model": "qwen-plus",
      "parameters": {}
    },
    "stateful": true,
    "permission_mode": "dont_ask"
  }'
```

### Cron 表达式

标准 5 字段 cron 表达式：

```
┌───────────── 分 (0-59)
│ ┌─────────── 时 (0-23)
│ │ ┌───────── 日 (1-31)
│ │ │ ┌─────── 月 (1-12)
│ │ │ │ ┌───── 周几 (0-6, 0=周日)
│ │ │ │ │
* * * * *
```

| 表达式 | 含义 |
|--------|------|
| `0 9 * * *` | 每天早上 9 点 |
| `0 9 * * 1-5` | 工作日早上 9 点 |
| `*/30 * * * *` | 每 30 分钟 |
| `0 0 1 * *` | 每月 1 号零点 |

### Stateful vs Stateless

| | Stateful | Stateless |
|---|----------|-----------|
| 会话 | 每次触发复用同一个 Session | 每次触发创建新 Session |
| 上下文 | 保留之前的对话历史 | 无历史，从零开始 |
| 适用场景 | 趋势对比、持续监控 | 独立报告、一次性任务 |
| 内存 | 随时间增长（需要压缩） | 固定开销 |

**Stateful 模式**：Agent 记住之前的分析结果，可以做趋势对比

```
第 1 天："上周总收入 $50,000"
第 2 天："今天总收入 $55,000，环比增长 10%"（因为记得昨天的数据）
```

**Stateless 模式**：每次都是全新开始

```
第 1 天："总收入 $50,000"
第 2 天："总收入 $55,000"（没有之前的对比）
```

### 权限模式

定时任务默认使用 `DONT_ASK` 模式（Tutorial 07），因为：

- 用户不在场，无法回答确认提示
- ASK 决策自动转为 DENY，防止阻塞
- 必要操作必须由工具自身明确返回 ALLOW，或通过 Allow 规则预先授权

```python
# 定时任务的推荐配置
{
    "permission_mode": "dont_ask",  # 或 "bypass"（测试环境）
}
```

### Agent 自主创建定时任务

Agent 可以通过 `ScheduleCreate` 工具自己创建定时任务：

```
用户：帮我设置一个每天早上 9 点生成销售日报的定时任务
Agent：好的，我来创建定时任务...
  >> Calling: ScheduleCreate
  >> {"name": "Daily Report", "cron_expression": "0 9 * * *", ...}
Agent：已创建定时任务 "Daily Report"，每天 9:00 自动执行。
```

## 示例：定时销售报告

本期展示如何通过 API 创建和管理定时任务，包括：

1. 创建 Stateless 定时任务，每次调用 T13 的只读销售工具独立生成摘要
2. 创建 Stateful 定时任务，在保留历史上下文的同时重新查询销售数据
3. 查看和管理定时任务

## 运行示例

本期的 `main.py` 是一段真实 httpx 客户端代码，不再只是打印说明。直接依赖 T13 的服务（默认使用本地 SQLite，**无需 Redis**）：

```bash
# 终端 A：启动服务
cd tutorials/13_agent_service && python main.py

# 终端 B：跑 T14 的 schedule CRUD 演示
cd tutorials/14_scheduling && python main.py
```

执行后会顺序：
1. 注册 Credential + DataMuse Agent 模板
2. 用无效 cron 验证服务返回 422 且不持久化
3. `POST /schedule/` 创建一条 Stateless 任务（默认 cron `*/5 * * * *`）
4. `POST /schedule/` 创建一条 Stateful 任务（默认 cron `*/10 * * * *`）
5. `GET /schedule/` 列出所有任务
6. `GET /schedule/{id}/sessions` 查看每个任务触发的会话

默认会在结尾 `DELETE` 清掉两条任务方便重复实验；想保留并等真正触发，加 `CLEANUP=0 python main.py`，几分钟后再访问 `GET /schedule/{id}/sessions` 就能看到自动执行的会话。

## 进一步探索

- 创建一个 Stateful 定时任务，观察多次触发后的上下文压缩
- 用 BYPASS 模式运行定时任务，与 DONT_ASK 模式对比行为
- 实现一个监控类定时任务：定期检查文件变化
- 通过 API 动态启用/停用定时任务

> 无人值守跑久了，模型限流或临时挂掉是必发生的事。Schedule 创建时至少要选一个稳定的 `chat_model_config`；如果是普通 Session，可以按 T13 的方式额外配置 `fallback_chat_model_config`。详见 **[T13 → 模型 fallback 与自动重试](../13_agent_service/README.md#模型-fallback-与自动重试)**。

## 下一期预告

**Tutorial 15: Multi-Agent** — 多 Agent 协作，实现数据采集 → 分析 → 报告的流水线。
