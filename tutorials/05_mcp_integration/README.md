# Tutorial 05: MCP 集成 — 连接外部工具服务器

> **什么时候需要这个？** 你需要的能力别人已经做成了 MCP server——数据库、浏览器、文件系统、各种 API——与其自己重新写一遍 `ToolBase`，不如直接接进来。MCP 让 Agent 一次性接入整个外部工具生态。

## 本章基于前序章节

- **T03 — `Toolkit`**：MCP 客户端通过 `Toolkit(mcps=[...])` 注册，和本地工具混在一起。
- **T04 — `ToolGroup`**：MCP 同样可以放进工具组，随组激活/停用。

## 你将学到

- MCP 协议的基本概念和价值
- `StdioMCPConfig` 与 `HttpMCPConfig` 两种连接方式
- Stateful（有状态）与 Stateless（无状态）连接的区别
- MCP 工具的命名空间规则：`mcp__{server}__{tool}`
- `enable_tools` / `disable_tools` 过滤机制
- MCP 工具与本地工具的混合使用

## 前置要求

- 完成 Tutorial 04
- MCP 客户端依赖已包含在基础安装中；如需运行示例里的 Stdio MCP 服务器，请安装 Node.js / `npx`
- （可选）安装 Node.js 以使用 Stdio MCP 服务器

## 核心概念

### 什么是 MCP？

MCP（Model Context Protocol）是一个标准化的工具服务接口协议。它允许 Agent 通过统一的协议连接各种外部工具服务器——数据库、浏览器、文件系统、API 等。

AgentScope 通过 `MCPClient` 提供对 MCP 的完整支持，让你可以轻松地将 MCP 服务器注册为 Agent 的工具。

### MCPClient

`MCPClient` 是 AgentScope 中的 MCP 客户端，它支持两种连接方式：

```python
from agentscope.mcp import MCPClient, StdioMCPConfig, HttpMCPConfig

# 方式 1: Stdio — 本地进程通信
client = MCPClient(
    name="filesystem",
    is_stateful=True,         # Stdio 必须是 stateful
    mcp_config=StdioMCPConfig(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    ),
)

# 方式 2: HTTP — 远程服务通信
client = MCPClient(
    name="weather",
    is_stateful=False,        # HTTP 可以是 stateless
    mcp_config=HttpMCPConfig(
        url="https://api.example.com/mcp",
        headers={"Authorization": "Bearer xxx"},
        timeout=30.0,
    ),
)
```

### Stateful vs Stateless

| 特性 | Stateful | Stateless |
|------|----------|-----------|
| 连接管理 | 需要 `connect()` / `close()` | 无需手动管理 |
| 会话持久 | 保持长连接 | 每次调用创建临时会话 |
| 适用传输 | Stdio 和 HTTP | 仅 HTTP |
| 性能 | 更高（复用连接） | 每次有连接开销 |
| 典型场景 | 本地 MCP 服务器 | 远程 API 服务 |

**关键规则**：Stdio MCP **必须**是 stateful（因为需要管理子进程）。HTTP MCP 可以是 stateful 或 stateless。

### 工具命名空间

MCP 工具在注册后会自动加上命名空间前缀：

```
mcp__{server_name}__{tool_name}
```

例如，名为 `filesystem` 的 MCP 服务器提供的 `read_file` 工具，注册后名称变为 `mcp__filesystem__read_file`。这样可以避免不同 MCP 服务器之间的工具名冲突。

### 工具过滤

通过 `enable_tools` 和 `disable_tools` 参数，你可以精确控制暴露给 Agent 的工具：

```python
# 只启用特定工具
client = MCPClient(
    name="filesystem",
    is_stateful=True,
    mcp_config=StdioMCPConfig(...),
    enable_tools=["read_file", "list_directory"],  # 仅这两个工具可用
)

# 禁用特定工具
client = MCPClient(
    name="filesystem",
    is_stateful=True,
    mcp_config=StdioMCPConfig(...),
    disable_tools=["write_file", "delete_file"],  # 排除危险操作
)
```

**注意**：`enable_tools` 和 `disable_tools` 不可同时指定有交集的工具。

### MCP 与本地工具混合

MCP 工具和本地工具可以自由组合在 `Toolkit` 中：

```python
toolkit = Toolkit(
    tools=[Read(), Glob()],           # 本地工具（basic 组）
    mcps=[filesystem_client],         # MCP 工具（basic 组）
    tool_groups=[
        ToolGroup(
            name="analysis",
            tools=[SalesSummary()],    # 本地工具
            mcps=[database_client],    # MCP 工具
        ),
    ],
)
```

MCP 工具同样支持 ToolGroup 的动态激活/停用机制。

### 生命周期管理

对于 stateful MCP 客户端，需要在使用前后正确管理连接：

```python
# 连接
await client.connect()

# ... 使用 agent ...

# 关闭（建议放在 try/finally 中）
await client.close()
```

**重要**：将 stateful MCP 客户端传入 `Toolkit` 之前，必须先调用 `connect()`，否则会抛出 `ValueError`。

## 示例：给 DataMuse 接入 MCP 服务

本期展示两种 MCP 接入方式：

1. **Stdio MCP**：连接本地文件系统 MCP 服务器，让 DataMuse 通过 MCP 浏览文件
2. **模拟 MCP**：展示如何配置 HTTP MCP 以及工具过滤的使用方式

由于 MCP 服务器需要外部依赖（Node.js），示例中提供了优雅的降级处理——当 MCP 不可用时，自动切换到本地工具演示。

## 运行示例

```bash
cd tutorials/05_mcp_integration
python main.py
```

如需体验 Stdio MCP（需要 Node.js）：

```bash
npm install -g @modelcontextprotocol/server-filesystem
python main.py
```

## 进一步探索

- 连接一个数据库 MCP 服务器（如 `@modelcontextprotocol/server-sqlite`）
- 将 MCP 客户端放入 ToolGroup，观察激活/停用行为
- 使用 `enable_tools` 和 `disable_tools` 实现最小权限暴露
- 比较 stateful 和 stateless HTTP MCP 的性能差异

## 下一期预告

**Tutorial 06: Skill** — 用 Markdown 指令集扩展 Agent 的能力，让 DataMuse 学会生成图表和分析报告。
