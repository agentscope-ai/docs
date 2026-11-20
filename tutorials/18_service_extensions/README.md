# Tutorial 18: Agent Service 扩展与部署边界

> **什么时候需要这个？** T13 的 REST + SSE 已经跑通，接下来要加入知识库、能力
> 市场、消息渠道，或把单进程服务扩成多个 API / worker 副本时，需要明确哪些
> 组件负责持久化、实时传输和后台任务，以及每个 worker 开关由谁持有。

## 本章基于前序章节

- **T12 — WorkspaceManager**：服务为 Session 分配真实工作空间。
- **T13 — Agent Service**：复用 Credential → Agent → Session → Chat 主链路。
- **T14 — Schedule**：调度 timer 只能由一个进程持有。
- **T17 — KnowledgeBase / RAG**：把本地知识链路升级成服务端上传和索引。

## 你将学到

- SQL Storage 与 MessageBus 为什么是两个独立组件
- Knowledge Base API 与 index worker 的部署方式
- MCP Hub、Skill Hub、Channel 和 Workspace API 的职责
- `enable_scheduler`、`enable_index_worker`、`enable_channel_worker`
- 多副本部署时必须显式配置的边界

## 单进程扩展服务

本章 `main.py` 使用：

- `AsyncSQLAlchemyStorage + SQLite` 保存服务数据
- `InMemoryMessageBus` 传递当前进程内的实时事件
- `LocalWorkspaceManager` 管理 Session 工作目录
- `CollectionPerKbManager + QdrantStore` 开启 Knowledge Base API
- `GitHubMCPHub + ClawSkillHub` 开启可浏览、可安装的能力 Hub

```bash
conda activate agentscope-tutorial
pip install -e ".[service,storage-sql,rag,vdb-qdrant]" aiosqlite
cd tutorials/18_service_extensions
python main.py
```

打开 `http://localhost:8001/docs` 查看完整 OpenAPI。没有配置模型 API Key 也可以
启动并浏览 schema；真正创建 embedding 或聊天任务时才需要相应 Credential。

## 路由与能力

| 路由 | 负责什么 |
|---|---|
| `/workspace` | 文件、下载、Session Workspace 内的 MCP / Skill |
| `/mcp` / `/skill` | 用户已经安装的能力库 |
| `/hub` | 从远端 MCP / Skill Hub 搜索并安装能力 |
| `/knowledge_bases` | 创建知识库、上传文档、查看索引状态 |
| `/embedding-model` | Embedding 模型 schema |
| `/channels` | 注册并管理钉钉、飞书、Discord 等渠道 |
| `/health` | API 与后台组件的健康状态 |

Hub 是“发现和安装”，Workspace 是“当前 Session 实际装备了什么”，两者不要混为
一谈。Channel 也不是普通聊天路由：它负责长连接或 webhook，把外部平台消息映射
到 Session。

## 三类后台 owner

| 开关 | 后台职责 | 多副本建议 |
|---|---|---|
| `enable_scheduler` | 持有 cron timers | 仅一个进程为 `True` |
| `enable_index_worker` | 消费文档索引任务 | 内嵌模式一个 owner，或单独部署 worker |
| `enable_channel_worker` | 持有渠道长连接 | 每个 bot/channel 只让一个 worker 连接 |

这些开关只控制后台 worker，不会删除对应 HTTP API。API 副本仍可把记录写入共享
Storage，并通过跨进程 MessageBus 通知 owner。

## 从单进程到多副本

本章配置只适合本地单进程。扩容时至少做以下替换：

| 本地示例 | 多副本部署 |
|---|---|
| SQLite | PostgreSQL 等共享 SQL 数据库 |
| InMemoryMessageBus | RedisMessageBus 等跨进程总线 |
| 本地 Qdrant memory | 远程共享向量数据库 |
| LocalWorkspaceManager | 共享存储或隔离沙箱 Manager |
| 随机 `download_secret` | 所有副本共享的固定 secret |

不要只把 Uvicorn worker 数量调大：否则 SSE 唤醒、定时任务、索引任务、Channel
连接和 Workspace 文件都可能落到不同进程，造成重复执行或读取不到状态。

## Channel 与资源访问策略

Channel 是显式注册的可选能力，例如：

```python
from agentscope.app.channel import DingTalkChannel, FeishuChannel

app = create_app(
    ...,
    channels=[DingTalkChannel, FeishuChannel],
    enable_channel_worker=True,
)
```

跨用户共享 Agent、Credential 或 Knowledge Base 时，还应提供自定义
`ResourceAccessPolicyBase`。默认策略是 owner 隔离，不会因为知道资源 ID 就允许
访问。

至此，教程覆盖了从本地 Agent、Tool 与审批，到 Workspace、服务、调度、团队、
RAG 和扩展部署边界的完整路径。
