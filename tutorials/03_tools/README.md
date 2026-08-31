# Tutorial 03: Tool 系统 — 赋予 Agent 行动能力

> **什么时候需要这个？** 单纯聊天不够了，你要让 Agent 真正做事——读 CSV、跑 Python 脚本、查数据库、调用任何具体动作。Tool 是 Agent 从"会说"走向"会做"的分水岭，后面几乎所有章节都是在这套工具体系之上加约束、加组合、加管理。

## 本章基于前序章节

- **T01 — Agent / Toolkit 槽位**：在 T01 的 Agent 上挂载 `Toolkit`，让它具备行动能力。
- **T02 — `ToolCallBlock` / `ToolResultBlock` / 工具事件**：理解工具调用在事件流里长什么样。

## 你将学到

- Toolkit 架构及其注册、管理、调度机制
- 内置工具（Bash, Read, Write, Edit, Glob, Grep）的使用
- `FunctionTool` 适配器：将 Python 函数快速变为 Agent 工具
- 自定义 `ToolBase` 子类：完整控制权限和执行逻辑
- 工具执行流程：Schema 验证 → 权限检查 → 执行 → 结果返回

## 前置要求

- 完成 Tutorial 01-02
- 准备好 `tutorials/data/sales_data.csv`（仓库已包含；如需重新生成可运行 `tutorials/data/generate_sales_data.py`）

## 核心概念

### Toolkit 架构

`Toolkit` 是 Agent 工具能力的**注册表和发现入口**，负责：

- **注册**：接受 `ToolBase` 实例、MCP 客户端、Skill 加载器，全部并入同一个工具池
- **发现**：根据当前激活的工具组，通过 `get_tool_schemas()` 把可用工具的 JSON Schema 提供给 LLM
- **定位与调用**：按工具名找到对应实现，并把调用结果统一为 Agent 可消费的工具结果

Schema 校验、权限判定，以及根据 `is_concurrency_safe` 决定并行或串行执行，发生在 Agent 的 acting 流程里。也就是说，Toolkit 管“有哪些工具、当前能看见哪些、具体调用谁”，Agent 管“一次 ReAct 迭代里如何安全地执行这些调用”。

创建 Toolkit 时可以传入 4 类来源，每一类都对应后续的一章：

```python
from agentscope.tool import Toolkit, Bash, Read

toolkit = Toolkit(
    tools=[Bash(), Read()],         # 本章：ToolBase 实例
    mcps=[],                        # T05：MCP 客户端
    skills_or_loaders=[],           # T06：Skill 加载器
    tool_groups=[],                 # T04：工具分组，运行时动态切换
)
```

不传 `tool_groups` 时，前三类工具会被自动收进一个名为 `"basic"` 的默认组。

> **条件出现的内置元工具**：当存在非 `basic` 工具组时，Schema 中会出现 `reset_tools`，用于切换工具组；当当前可用组中存在 Skill 时，会出现 `Skill`，用于按名称读取完整 Skill 指令。它们不是每个 Toolkit 都固定拥有的两个工具，具体条件分别在 T04、T06 展开。

### 内置工具

AgentScope 2.0 提供了一组开箱即用的工具：

| 工具 | 功能 | 只读 |
|------|------|------|
| `Bash` | 执行 Shell 命令 | 否 |
| `Read` | 读取文件内容（带行号） | 是 |
| `Write` | 创建/覆写文件 | 否 |
| `Edit` | 精确字符串替换 | 否 |
| `Glob` | 按 glob 模式查找文件 | 是 |
| `Grep` | 搜索文件内容（ripgrep） | 是 |

**重要规则**：`Write` 和 `Edit` 要求文件必须先被 `Read` 读取过，防止盲写。

### FunctionTool 适配器

最快的方式是用 `FunctionTool` 包装一个普通 Python 函数：

```python
from agentscope.tool import FunctionTool

def query_sales(category: str, min_total: float = 0.0) -> str:
    """Query sales data by category and minimum total.

    Args:
        category: Product category to filter by.
        min_total: Minimum order total to include.
    """
    # ... implementation
    return result_string

tool = FunctionTool(query_sales, is_read_only=True)
```

`FunctionTool` 自动从函数签名和 docstring 提取：
- `name` ← 函数名
- `description` ← docstring 摘要
- `input_schema` ← 参数类型注解和 Args 描述

普通函数可以直接返回 `str` / `dict` / list，`FunctionTool` 会自动转换为 Agent 能消费的 `ToolChunk`。只有需要流式输出、多模态结果或精细状态时，才手动返回 `ToolChunk`。

### 自定义 ToolBase

需要完整控制权限和执行逻辑时，继承 `ToolBase`：

```python
from agentscope.tool import ToolBase, ToolChunk
from agentscope.permission import PermissionContext, PermissionDecision, PermissionBehavior
from agentscope.message import TextBlock

class MyTool(ToolBase):
    name = "MyTool"
    description = "..."
    input_schema = { ... }
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(self, tool_input, context):
        return PermissionDecision(behavior=PermissionBehavior.ALLOW)

    async def call(self, **kwargs):
        result = do_something(**kwargs)
        return ToolChunk(content=[TextBlock(text=str(result))])
```

自定义工具推荐覆写 `call()`。`ToolBase.__call__()` 由框架保留，用来包住 tool-level middleware；直接覆写 `__call__()` 会绕过这层包装。

### 工具执行流程

```
LLM 生成 ToolCallBlock
  ↓
Schema 验证（jsonschema.validate）
  ↓ 失败 → 返回错误给 LLM
权限检查（check_permissions + PermissionEngine）
  ↓ DENY → 返回拒绝信息给 LLM
  ↓ ASK  → 暂停等待用户确认
  ↓ ALLOW → 继续执行
工具执行（ToolBase.__call__ → tool middleware → call）
  ↓
结果返回到 Agent 上下文
  ↓
LLM 继续推理
```

## 示例：给 DataMuse 装上数据分析工具

本期我们给 DataMuse 添加三层工具能力：
1. **内置工具**：让它读取 CSV 文件、执行 Python 脚本
2. **FunctionTool**：封装一个数据查询函数
3. **自定义 ToolBase**：实现一个带统计计算的分析工具

## 运行示例

```bash
cd tutorials/03_tools
python main.py
```

## 进一步探索

- 尝试给 `FunctionTool` 添加 `is_read_only=True` 参数观察权限行为变化
- 自定义一个支持流式输出的工具（`async def call` 返回 `AsyncGenerator`）
- 观察并发安全工具和非并发安全工具在多工具调用时的执行差异

## 下一期预告

**Tutorial 04: Tool Group** — 将工具按功能域分组，让 DataMuse 根据任务自动切换工具集。
