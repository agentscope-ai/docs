# Tutorial 12: Workspace — Agent 的工作空间

> **什么时候需要这个？** 当你不想再手动一个一个拼装 `Tool` / `MCP` / `Skill` / `Offloader`，或者你要把 Agent 部署到多用户、多 Session 场景，每个 Session 需要一个隔离的执行环境（内置工具、持久化目录、独立 MCP）——Workspace 就是把这些东西收束成一个统一对象。

## 本章基于前序章节

- **T03 — 内置工具（Bash/Read/Write/Edit/Glob/Grep）**：Workspace 自动注入这些工具，无需手动列。
- **T05 — MCP**：Workspace 通过 `add_mcp` / `remove_mcp` 统一管理 MCP 客户端。
- **T06 — Skill / `LocalSkillLoader`**：Workspace 提供 `add_skill` / `list_skills` 等 Skill 管理接口。
- **T10 — `Offloader` 协议**：Workspace 同时实现 Offloader，把压缩的上下文和截断的工具结果落到本地目录。

## 你将学到

- Workspace 的设计定位：工具、MCP、Skill 和 Offload 的统一载体
- `LocalWorkspace`：目录布局、初始化、生命周期
- Workspace 如何自动注入内置工具（Bash、Read、Write、Edit、Glob、Grep）
- Workspace 作为 Offloader：上下文和工具结果的持久化
- MCP 和 Skill 的动态管理：`add_mcp` / `remove_mcp`、`add_skill` / `remove_skill`
- Docker / E2B / K8s Workspace 的对比（概念介绍）
- Workspace 在 Agent Service 中的角色

## 前置要求

- 完成 Tutorial 01-11
- 理解 MCP（Tutorial 05）、Skill（Tutorial 06）、ContextConfig（Tutorial 10）的基本概念

## 核心概念

### 为什么需要 Workspace？

在前面的教程中，我们分别学了工具、MCP、Skill、Context 压缩。它们在代码中是分散的：

```python
# 以前的做法：手动拼装
agent = Agent(
    toolkit=Toolkit(
        tools=[Bash(), Read(), Write(), ...],      # 手动列工具
        skills_or_loaders=[LocalSkillLoader(...)],  # 手动加 Skill
        mcps=[MCPClient(...)],                      # 手动加 MCP
    ),
    offloader=some_offloader,                       # 手动配 Offloader
)
```

Workspace 把这些收束到一个统一的抽象里：

```python
# Workspace 的做法：一个对象管所有
workspace = LocalWorkspace(workdir="./workspace")
await workspace.initialize()

agent = Agent(
    toolkit=Toolkit(
        tools=await workspace.list_tools(),       # 自动提供内置工具
        skills_or_loaders=await workspace.list_skills(),
        mcps=await workspace.list_mcps(),
    ),
    offloader=workspace,                          # 同时也是 Offloader
)
```

### WorkspaceBase 协议

```python
class WorkspaceBase:
    # 生命周期
    async def initialize() -> None
    async def close() -> None
    async def reset() -> None

    # Agent 消费：资源发现
    async def list_tools() -> list[ToolBase]
    async def list_mcps() -> list[MCPClient]
    async def list_skills() -> list[Skill]
    async def get_instructions() -> str

    # Agent 消费：Offload
    async def offload_context(session_id, msgs) -> str
    async def offload_tool_result(session_id, tool_result) -> str

    # 用户操作：动态管理
    async def add_mcp(mcp_client) -> None
    async def remove_mcp(name) -> None
    async def add_skill(skill_path) -> None
    async def remove_skill(name) -> None
```

### LocalWorkspace 目录布局

```
workspace/
├── .mcp              ← MCP 配置持久化（JSON）
├── data/             ← Offload 的多模态文件（图片等）
├── skills/           ← 技能目录（每个技能一个子目录）
│   ├── .skills       ← 技能索引文件
│   └── chart_gen/
│       └── SKILL.md
└── sessions/         ← 按 session_id 分区
    └── {session_id}/
        ├── context.jsonl               ← 压缩后的上下文
        └── tool_result-{id}.txt        ← Offload 的工具结果
```

### Workspace 的三个角色

| 角色 | 方法 | 说明 |
|------|------|------|
| 工具提供者 | `list_tools()` | 返回 Bash、Read、Write、Edit、Glob、Grep |
| 资源管理者 | `list_mcps()`, `list_skills()` | MCP 和 Skill 的注册/发现 |
| Offloader | `offload_context()`, `offload_tool_result()` | 上下文压缩和工具结果持久化 |

### 三种 Workspace 实现

| 实现 | 隔离级别 | 适用场景 |
|------|----------|----------|
| `LocalWorkspace` | 目录级别 | 本地开发、教程、单用户 |
| `DockerWorkspace` | 容器级别 | 单机服务、多租户隔离 |
| `E2BWorkspace` | 云沙箱 | SaaS 场景、完全隔离 |
| `K8sWorkspace` | Pod / PVC 级别 | 已有 Kubernetes 集群，需要按 Session 管理 Pod 生命周期 |

本教程聚焦 `LocalWorkspace`。Docker、E2B、K8s 的使用方式相同：在 Agent Service 里换成对应的 `WorkspaceManager`，由它负责为每个 Session 分配工作空间。

```python
from agentscope.app.workspace_manager import (
    LocalWorkspaceManager,
    DockerWorkspaceManager,
    E2BWorkspaceManager,
    K8sWorkspaceManager,
)
```

## 示例

本期演示 LocalWorkspace 的完整功能：初始化、内置工具、Skill 管理、Offloader 集成，以及用 Agent 在 Workspace 中完成一次数据分析任务。

## 运行示例

```bash
cd tutorials/12_workspace
python main.py
```

## 进一步探索

- 用 `add_mcp()` 在运行时动态添加一个 MCP server
- 观察 `sessions/` 目录下的 offload 文件内容
- 自定义 `instructions` 参数，改变 Agent 对 Workspace 的理解
- 对比 `LocalWorkspace`、`DockerWorkspace` 和 `K8sWorkspace` 的隔离差异

## 下一期预告

**Tutorial 13: Agent Service** — 将 Workspace 作为 Agent Service 的执行环境，部署多用户多会话的 HTTP 服务。
