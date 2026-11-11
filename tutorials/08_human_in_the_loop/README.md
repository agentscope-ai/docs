# Tutorial 08: Human-in-the-Loop — 人机协作

> **什么时候需要这个？** T07 的权限引擎已经会返回 ASK 了，本章告诉你 ASK 之后怎么办——如何实现"暂停 → 把待确认的工具调用展示给用户 → 收到回复 → 恢复执行"的完整循环。同样的机制也适用于"外部工具"场景（发邮件、上线服务等需要外部系统执行的操作）。

## 本章基于前序章节

- **T02 — Event 系统**：本章的 `RequireUserConfirmEvent` / `UserConfirmResultEvent` 都是 T02 介绍过的事件类型。
- **T07 — 权限 ASK 行为 / `PermissionRule`**：ASK 是触发 HITL 的来源；`ConfirmResult.rules` 用来实现渐进式信任。

## 你将学到

- 两种暂停场景：用户确认（ASK）和外部执行（External Tool）
- `RequireUserConfirmEvent` → `UserConfirmResultEvent` 确认流程
- `RequireExternalExecutionEvent` → `ExternalExecutionResultEvent` 外部执行流程
- `ConfirmResult` 的构造和 `suggested_rules` 的使用
- 如何实现一个终端交互确认界面

## 前置要求

- 完成 Tutorial 07
- 理解权限系统的 ASK 行为

## 核心概念

### Agent 的暂停与恢复

在 Tutorial 07 中，我们看到权限检查可能返回 ASK——需要用户确认。当这发生时，Agent 的 `reply_stream()` 会 yield 一个特殊事件，然后**暂停执行**，等待外部输入后恢复。

AgentScope 支持两种暂停场景：

```
场景 1: 用户确认（ASK）
─────────────────────
Agent 想执行工具 → 权限 ASK → yield RequireUserConfirmEvent
  → 暂停，等待用户输入
  → 用户确认/拒绝 → 构造 UserConfirmResultEvent
  → 调用 reply_stream(event) 恢复 Agent

场景 2: 外部执行（External Tool）
──────────────────────────────
Agent 调用外部工具 → yield RequireExternalExecutionEvent
  → 暂停，等待外部执行结果
  → 外部系统执行完毕 → 构造 ExternalExecutionResultEvent
  → 调用 reply_stream(event) 恢复 Agent
```

### RequireUserConfirmEvent

当权限引擎返回 ASK 时，Agent 会 yield 此事件：

```python
class RequireUserConfirmEvent:
    type: EventType.REQUIRE_USER_CONFIRM
    reply_id: str               # 关联的回复 ID
    tool_calls: list[ToolCallBlock]  # 待确认的工具调用
```

`tool_calls` 列表中的每个 `ToolCallBlock` 包含工具名称和输入参数。

### ConfirmResult

用户确认后，需要构造 `ConfirmResult` 对象：

```python
from agentscope.event import ConfirmResult

# 确认执行
result = ConfirmResult(
    confirmed=True,
    tool_call=tool_call_block,
    rules=None,        # 可选：接受建议的权限规则
)

# 拒绝执行
result = ConfirmResult(
    confirmed=False,
    tool_call=tool_call_block,
)
```

`rules` 字段允许用户在确认时附带权限规则，实现**渐进式信任**：

```python
from agentscope.permission import PermissionRule, PermissionBehavior

result = ConfirmResult(
    confirmed=True,
    tool_call=tool_call_block,
    rules=[
        PermissionRule(
            tool_name="Bash",
            rule_content="python",
            behavior=PermissionBehavior.ALLOW,
            source="user_confirm",
        ),
    ],
)
```

### UserConfirmResultEvent

将 `ConfirmResult` 包装为事件，传回 Agent：

```python
from agentscope.event import UserConfirmResultEvent

event = UserConfirmResultEvent(
    reply_id=require_event.reply_id,
    confirm_results=[result1, result2, ...],
)

# 恢复 Agent 执行
async for event in agent.reply_stream(event):
    ...
```

### External Tool（外部工具）

当 `ToolBase.is_external_tool = True` 时，Agent 不会执行工具的 `call()`，而是 yield `RequireExternalExecutionEvent`，等待外部系统提供执行结果：

```python
class ExternalExecutionResultEvent:
    type: EventType.EXTERNAL_EXECUTION_RESULT
    reply_id: str
    execution_results: list[ToolResultBlock]
```

典型场景：发送邮件、部署服务、调用需要人工操作的 API。

### 完整交互循环

```python
async for event in agent.reply_stream(user_msg):
    match event.type:
        case EventType.REQUIRE_USER_CONFIRM:
            # 展示待确认的工具调用给用户
            # 获取用户的确认/拒绝
            confirm_event = build_confirm_event(event)
            # 恢复 Agent
            async for evt in agent.reply_stream(confirm_event):
                handle_event(evt)

        case EventType.REQUIRE_EXTERNAL_EXECUTION:
            # 外部系统执行工具
            results = await execute_externally(event.tool_calls)
            exec_event = build_execution_event(event, results)
            # 恢复 Agent
            async for evt in agent.reply_stream(exec_event):
                handle_event(evt)

        case EventType.TEXT_BLOCK_DELTA:
            print(event.delta, end="")
```

## 示例：交互式确认界面

本期实现一个终端交互式确认 UI，展示：

1. **用户确认场景**：Agent 想执行 Bash 命令，权限要求确认，用户选择同意或拒绝
2. **外部执行场景**：Agent 调用一个外部工具，外部系统提供执行结果
3. **渐进式信任**：确认时接受建议规则，后续同类操作自动允许

## 运行示例

```bash
cd tutorials/08_human_in_the_loop
python main.py
```

## 进一步探索

- 实现一个 Web UI 的确认界面（使用 SSE 推送确认请求）
- 创建一个自定义外部工具（如"发送邮件"），模拟外部执行流程
- 将 HITL 与 Permission 规则结合：第一次确认后自动添加 Allow 规则
- 尝试部分确认：同一批次的多个工具调用中，只确认部分

## 下一期预告

**Tutorial 09: 流式 UI** — 利用完整的 Event 系统构建一个功能丰富的终端 UI，包括进度指示、token 统计和折叠展示。
