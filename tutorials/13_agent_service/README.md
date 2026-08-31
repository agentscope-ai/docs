# Tutorial 13: Agent Service — 服务化部署

> **什么时候需要这个？** 单脚本跑通后，你要把 Agent 暴露成 HTTP 服务：支持多用户隔离、多 Session 并行、状态持久化、Web/移动端通过 REST + SSE 接入。`create_app()` 提供 FastAPI 服务骨架，并在运行时组装模型、工具、Middleware 和 Workspace。

从本章开始，DataMuse 从“本地单 Agent”切换为“Agent Service”形态。业务目标和销售数据不变，但 Agent 模板、Session 状态、服务端能力和客户端调用被拆到不同层，不再沿用前面脚本的文件相对路径。

## 本章基于前序章节

- **T09 — 流式事件**：HTTP `/sessions/{id}/stream` 推送的就是 T09 渲染的那套 AgentEvent。
- **T10 — `ContextConfig`**：Session 创建时绑定的 context 配置。
- **T11 — Middleware**：服务端 Agent 同样可以挂中间件做日志/计费/tracing。
- **T12 — Workspace / `WorkspaceManager`**：每个 Session 通过 `WorkspaceManager` 拿到一个隔离的 Workspace。

## 你将学到

- `create_app()` 工厂函数的使用
- `MessageBus` 在服务端事件流里的作用
- 多租户架构：`user_id` 隔离
- Session 模型：Agent 模板 vs 运行时状态
- Credential 集中管理
- Chat 触发与 Session SSE 流式通信
- 模型 fallback、TTS、Knowledge Base 等 Session 级配置
- 连接官方示例 Web UI
- REST API 的完整流程

## 前置要求

- 完成 Tutorial 12
- 安装服务依赖：`pip install "agentscope[service]==2.0.4" fakeredis httpx`
- Redis 服务可选；本教程默认用 `fakeredis` 跑内存模式
- 如需体验 Web UI：Node.js 20+ 与 `pnpm`

## 核心概念

### 从脚本到服务

前面的教程都是单脚本运行的 Agent。在真实部署中，我们需要：

- **多用户**：不同用户的 Agent 相互隔离
- **多会话**：同一用户可以有多个对话
- **持久化**：重启后恢复状态
- **HTTP API**：Web/移动客户端可以接入

### create_app() 工厂函数

```python
from agentscope.app import create_app
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.storage import RedisStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager

app = create_app(
    storage=RedisStorage(host="localhost", port=6379),
    message_bus=InMemoryMessageBus(),
    workspace_manager=LocalWorkspaceManager(basedir="./workspaces"),
)
```

`create_app()` 返回一个 FastAPI 应用，内置以下路由：

| 路由前缀 | 功能 |
|----------|------|
| `/credential` | API Key 管理 |
| `/agent` | Agent 模板管理 |
| `/sessions` | 会话管理 |
| `/chat` | 触发一次对话运行 |
| `/sessions/{id}/stream` | 订阅会话事件流 |
| `/schedule` | 定时任务 |
| `/knowledge_bases` | Knowledge Base / RAG 管理（启用后可用） |
| `/tts_model` | TTS 模型 schema / 发现 |

`MessageBus` 是服务里的实时事件通道：`POST /chat/` 只负责触发 run，Agent 产生的事件会写入 bus，再由 `/sessions/{id}/stream` 以 SSE 推给客户端。单进程教程用 `InMemoryMessageBus()`；多进程或多 worker 部署时换成 `RedisMessageBus()`。

### 多租户架构

每个请求通过 `user_id` Header 标识用户：

```
Client → HTTP Request (X-User-Id: user123) → AgentScope Service
                                                 ↓
                                          user_id 隔离
                                          ├─ Credentials
                                          ├─ Agents
                                          └─ Sessions
```

### Agent 与 Session 的关系

```
Agent（模板）              Session（运行时）
├─ name                   ├─ session_id
├─ system_prompt          ├─ agent_id（关联模板）
├─ context_config         ├─ chat_model_config
└─ react_config           ├─ context（对话历史）
                            └─ state（权限、工具状态）
```

- **Agent** 是模板：定义了 Agent 的配置
- **Session** 是实例：每次对话创建一个 Session，包含独立的上下文和状态
- 同一个 Agent 模板可以创建多个 Session

### 完整 API 流程

```
1. POST /credential/                    ── 创建 API Key
2. POST /agent/                         ── 创建 Agent 模板
3. POST /sessions/                      ── 创建 Session 并绑定模型
4. GET  /sessions/{id}/stream           ── 打开 SSE 事件订阅
5. POST /chat/                          ── 发送消息，触发一次 run
6. GET  /sessions/{id}/status           ── 查看 running / idle / awaiting 状态
7. GET  /sessions/{id}/messages         ── 查看会话消息
```

### Web UI

AgentScope 2.0 仓库里包含一个配套 Web UI，位于 `examples/web_ui`。它不是 Python extra 的一部分，而是一个独立的前端示例，用来连接上面由 `create_app()` 启动的 Agent Service。

启动 Agent Service 后，在另一个终端运行：

```bash
cd examples/web_ui
pnpm install
pnpm dev
```

打开 Web UI 后，在 setup 页面把服务器地址填为 `http://localhost:8000`，用户名可以填 `demo-user`。后续创建 Credential、Agent、Session 和发送消息，都可以通过界面完成；这和下面的 `curl` 流程调用的是同一组后端 API。

### SSE 流式通信

`POST /chat/` 现在是**触发器**：请求成功只说明 run 已开始，不直接返回 AgentEvent。真正的 Server-Sent Events 流来自 `GET /sessions/{session_id}/stream?agent_id=...`：

```
GET /sessions/{session_id}/stream?agent_id={agent_id}
data: {"type": "REPLY_START", "reply_id": "xxx", ...}
data: {"type": "TEXT_BLOCK_DELTA", "delta": "Hello", ...}
data: {"type": "MODEL_CALL_END", "input_tokens": 100, ...}
data: {"type": "REPLY_END", ...}
```

所以客户端的顺序是：先建立 stream 长连接，再 `POST /chat/` 触发一次回复，收到 `REPLY_END` 后按需关闭连接。这样同一个 stream 可以跨多次 run 复用，也能支持 HITL 恢复、后台唤醒和 team worker 的事件投影。

### Workspace 隔离

`WorkspaceManager` 为每个 Session 提供隔离的工作环境：

| 类型 | 说明 |
|------|------|
| `LocalWorkspaceManager` | 本地目录隔离 |
| `DockerWorkspaceManager` | Docker 容器隔离 |
| `E2BWorkspaceManager` | E2B 沙箱隔离 |
| `K8sWorkspaceManager` | Kubernetes Pod / PVC 隔离 |

### 模型 fallback 与自动重试

服务化之后，模型挂掉/限流就不再是"重跑一次"能解决的事——请求来自真实用户或定时任务，必须**自动**降级或重试。AgentScope 有两层配置：

```python
from agentscope.agent import Agent
from agentscope.agent import ModelConfig
from agentscope.credential import DashScopeCredential
from agentscope.model import DashScopeChatModel

primary = DashScopeChatModel(
    credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
    model="qwen-plus",
)
backup = DashScopeChatModel(
    credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
    model="qwen-turbo",  # 便宜、稳定的兜底
)

agent = Agent(
    name="DataMuse",
    system_prompt="...",
    model=primary,
    model_config=ModelConfig(
        max_retries=2,        # 主模型先重试 2 次
        fallback_model=backup, # 还失败就切到 backup（backup 也享受 max_retries）
    ),
)
```

在 Agent Service 里，fallback 是 Session 级配置：

```json
{
  "agent_id": "agt_xxx",
  "chat_model_config": {
    "type": "dashscope_chat",
    "credential_id": "cred_primary",
    "model": "qwen-plus",
    "parameters": {}
  },
  "fallback_chat_model_config": {
    "type": "dashscope_chat",
    "credential_id": "cred_backup",
    "model": "qwen-turbo",
    "parameters": {}
  }
}
```

语义：
- `fallback_chat_model_config=None`（默认）→ 主模型失败后直接抛错
- 配了 fallback → 主模型失败后切到备用模型
- 每个具体 `ChatModelBase` 仍有自己的 API retry 逻辑；库模式下还可以通过 `ModelConfig(max_retries=...)` 控制 fallback 前的重试次数

什么时候配？
- **面向用户的 API 服务**：用户在等响应，必须有兜底
- **定时任务（T14）**：无人值守失败就只能等下次 cron，必须自动重试 + fallback
- **dev/exploration**：通常不需要——失败让它显式报错，反而能更快定位

### 给服务端 Agent 注入能力

`POST /agent/` 创建的是模板，HTTP payload 不能直接塞 Python 对象进去；但服务宿主可以在 `create_app()` 时注入运行期能力：

```python
app = create_app(
    ...,
    extra_agent_tools=tool_factory,          # 每次组装 Agent 时追加工具
    extra_agent_middlewares=middleware_factory,
)
```

这里的 factory 是异步函数，签名为 `(user_id, agent_id, session_id) -> list[ToolBase]`。它会在每次组装服务端 Agent 时执行，因此既可以返回固定工具，也可以按用户、Agent 或 Session 决定可用能力。

本教程同时展示两种注入方式：

- `extra_agent_tools=datamuse_tools`：注入固定读取服务端数据的 `SalesProfile` 和 `SalesBreakdown`。数据路径由服务宿主管理，客户端不需要知道文件系统结构。
- `LocalWorkspaceManager(skill_paths=[...])`：把 T06 的 `report_writer` Skill 放入每个隔离 workspace，让 Agent 按需读取写报告的操作指南。

二者职责不同：Tool 提供可直接调用的原子能力，Skill 提供如何组合能力的操作指南。

### Knowledge Base / TTS

新版本的 Agent Service 还支持两类 Session 级能力：

- `knowledge_config`：把 Knowledge Base 接到本 Session，底层通过 `RAGMiddleware` 检索并注入上下文。
- `tts_model_config`：把 TTS 模型接到本 Session，底层通过 `TTSMiddleware` 把文本回复合成为 `DATA_BLOCK_*` 音频事件。

它们都不是 DataMuse 主线的必要步骤，所以本章先点出接入位置；真正需要"带资料库问答"或"语音回复"时，再扩展这一层。

## 示例：部署 DataMuse 服务

本期展示如何用 `create_app` 创建一个完整的 Agent 服务，并用三种方式驱动它：`curl`、`client.py`（Python httpx）、Web UI。

Agent 模板只保存名称、系统提示词和运行配置；具体模型在创建 Session 时通过 `chat_model_config` 绑定。Python 工具不要放进 HTTP Agent payload，而是在服务宿主侧通过 `extra_agent_tools` 注入；MCP 和 Skill 则可以通过 Workspace 的 `default_mcps` / `skill_paths` 注入。本期 `main.py` 两种方式都用了：`SalesProfile` / `SalesBreakdown` 来自服务宿主，`report_writer` Skill 来自 Workspace。

> 默认存储用 `fakeredis` 跑内存模式，**无需启动真实 Redis**。实际部署时把 `_make_inmemory_storage()` 换成 `RedisStorage(host=..., port=...)` 即可。

## 运行示例

```bash
# 安装零依赖运行所需的两个小包
pip install fakeredis httpx

# 终端 A：启动服务（默认 8000，无 Redis 依赖）
cd tutorials/13_agent_service
python main.py

# 终端 B：用 Python httpx 走完 5 步 API 流程
cd tutorials/13_agent_service
python client.py
```

`client.py` 会依次：

1. `POST /credential/` — 用环境变量里的 `DASHSCOPE_API_KEY` / `OPENAI_API_KEY` 注册 Credential
2. `POST /agent/` — 创建 DataMuse Agent 模板
3. `POST /sessions/` — 建一个 Session 并绑定模型
4. `GET /sessions/{id}/stream` — 打开 SSE 事件流
5. `POST /chat/` — 触发一次回复
6. Agent 调用 `SalesProfile` / `SalesBreakdown`，客户端流式打印工具和文本事件
7. `GET /sessions/{id}/messages` — 列出已持久化的对话

如果偏好命令行，仍可用 curl —— `main.py` 的 `print_overview()` 会列出每一步的 endpoint。

如果要用 Web UI 体验同一个服务：

```bash
# 在仓库根目录的另一个终端
cd examples/web_ui
pnpm install
pnpm dev
```

Web UI 首次打开时填入 `http://localhost:8000` 和一个用户名即可。

## 进一步探索

- 挂载到已有的 FastAPI 应用中
- 配置 Docker Workspace 实现更强的隔离
- 自定义认证中间件替换默认的 `X-User-Id` Header
- 使用 `extra_credentials` 注册自定义 Credential 类型
- 使用 `extra_agent_tools` 做按用户/租户的工具注入
- 为 Session 配置 `knowledge_config` 或 `tts_model_config`

## 下一期预告

**Tutorial 14: Schedule** — 配置定时任务，让 DataMuse 自动生成日报。
