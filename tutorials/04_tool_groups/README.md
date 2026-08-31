# Tutorial 04: Tool Group — 动态工具管理

> **什么时候需要这个？** Agent 的工具一多，所有工具 Schema 都塞进上下文既浪费 token、又让 LLM 选错工具。把工具按"功能域"分组（数据 IO / 分析 / 可视化），让 Agent 按需切换，是工具数量上量后的标配做法。

## 本章基于前序章节

- **T03 — `Toolkit` / `ToolBase` / `FunctionTool`**：本章把 T03 的 `query_sales` 等工具按功能拆进不同 `ToolGroup`。

## 你将学到

- `basic` 保留组的特殊地位
- 如何定义和组织 ToolGroup
- `reset_tools` 元工具的工作原理
- Agent 自动切换工具组的最佳实践

## 前置要求

- 完成 Tutorial 03
- 理解 Toolkit 和 ToolBase 的基本概念

## 核心概念

### 为什么需要 Tool Group？

随着 Agent 配备的工具越来越多，所有工具的 JSON Schema 都会被发送给 LLM。这带来两个问题：

1. **上下文浪费**：大量不相关的工具描述消耗宝贵的 context window
2. **选择困难**：工具太多时 LLM 可能选错工具

ToolGroup 解决了这个问题：将工具按功能域分组，Agent 可以**按需激活/停用**工具组。

### basic 保留组

`basic` 是一个特殊的工具组：
- **始终激活**，不受 `reset_tools` 影响
- 当你直接传入 `tools=` 参数时，这些工具自动归入 `basic` 组
- 适合放入通用工具（Read, Write, Bash 等）

### ToolGroup 定义

```python
from agentscope.tool import ToolGroup

group = ToolGroup(
    name="analysis",
    description="Statistical analysis tools for computing summaries and trends.",
    instructions="Always validate input data before running analysis.",
    tools=[my_analysis_tool],
)
```

| 参数 | 说明 |
|------|------|
| `name` | 组名（`"basic"` 为保留名） |
| `description` | **必填**（basic 除外），Agent 用此决定是否激活 |
| `instructions` | 激活时返回给 Agent 的使用指南 |
| `tools` | 本组包含的工具列表 |
| `mcps` | 本组包含的 MCP 客户端 |
| `skills_or_loaders` | 本组包含的技能 |

### reset_tools 元工具

`reset_tools` 是 Toolkit 在你注册了非 basic 工具组时**自动注入**的一个元工具。LLM 通过调用它来切换自己当前激活的工具组——这是"agent 自管理工具集"的实现机制。

**它和 basic 工具的区别**

| | basic 工具 | reset_tools |
|---|---|---|
| 出现在 schema 里 | 总是 | 仅当存在至少一个非 basic 组时 |
| 归属哪个组 | `"basic"` 组 | **不属于任何组**（在 Toolkit 里单独占一个 `builtin_meta_tool` 槽） |
| 受组的激活状态影响 | basic 永远激活 | 不受影响——一旦被注入就一直可见 |
| 权限检查 | 跟普通工具一样走 PermissionEngine | 内置硬编码 `ALLOW`，用户规则改不掉 |

> 所以严格说"`reset_tools` 是不是 basic 工具" 的答案是**不是**——它和 basic 是并列的"始终可用"层，但走的是不同的注册路径。

**动态生成的 input schema**

`reset_tools` 没有静态 schema——它在每次调 `get_tool_schemas()` 时，根据当前 Toolkit 里的非 basic 组**动态生成**：每个组变成一个 `bool` 字段，字段 description 用的就是 `ToolGroup(description=...)`。所以 LLM 看到的是这样：

```json
{
  "name": "reset_tools",
  "parameters": {
    "data_io":       {"type": "boolean", "default": false, "description": "数据读写..."},
    "analysis":      {"type": "boolean", "default": false, "description": "统计分析..."},
    "visualization": {"type": "boolean", "default": false, "description": "图表生成..."}
  }
}
```

**调用语义**

- 每次调用 = **最终期望状态**（覆盖式，不是增量）。源码里第一步就是 `activated_groups.clear()`，然后把传 `True` 的组加进去
- 没显式传 `True` 的组都会被关掉——LLM 想保留某组必须每次都列上
- `basic` 组不出现在 schema 里，永远激活，关不掉
- 工具返回值是激活组的 `instructions` 文本（来自 `ToolGroup(instructions=...)`），LLM 收到后才知道这组该怎么用

**调用一次的完整流程**

```
LLM 决定要做可视化：
  reset_tools({"visualization": True})
      ↓
  ResetTools.call:
    1. activated_groups.clear()
    2. activated_groups = ["visualization"]
    3. 返回 visualization 组的 instructions 给 LLM
      ↓
  下一轮 LLM 看到的 toolkit schema：
    basic + reset_tools + visualization 组的工具
    （data_io / analysis 已经从 schema 里消失）
```

### 设计原则

- **按功能域分组**：数据读写、统计分析、可视化各一组
- **最小激活**：只激活当前任务需要的组
- **instructions 指导**：在组被激活时提供上下文相关的使用指南

## 示例：DataMuse 的三个工具组

本期将 DataMuse 的工具分为三个功能组：
1. **data_io** — 数据读写工具（Read, Glob, query_sales）
2. **analysis** — 统计分析工具（SalesSummary, Bash for Python scripts）
3. **visualization** — 图表生成工具（Bash for matplotlib）

Agent 会根据用户的请求自动切换到合适的工具组。

## 运行示例

```bash
cd tutorials/04_tool_groups
python main.py
```

## 进一步探索

- 将 MCP 客户端放入工具组，观察激活/停用行为
- 创建一个包含 Skill 的工具组
- 增加组数量，观察 Agent 在复杂场景下的组切换决策

## 下一期预告

**Tutorial 05: MCP 集成** — 通过 MCP 协议连接外部工具服务器，让 DataMuse 访问数据库和网页。
