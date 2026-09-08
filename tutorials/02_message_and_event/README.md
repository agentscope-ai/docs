# Tutorial 02: Message & Event — Agent 的通信协议

> **什么时候需要这个？** 你要做 UI、做日志、做调试，需要看清 Agent 内部到底发生了什么；或者你想理解 `reply_stream()` 返回的事件长什么样、怎么从事件流重建一条消息。后面所有"流式 UI / 中间件 / 服务" 都依赖你看懂这套协议。

## 本章基于前序章节

- **T01 — Agent 与 `reply_stream`**：本章在 T01 的最小 Agent 之上，深入看它产出的事件流和最终消息。

## 你将学到

- `Msg` 消息的完整结构和六种 ContentBlock
- Event 事件系统的分块事件与一次性事件
- 消息-事件对偶性：事件流如何重建完整消息
- 用 `append_event()` 从事件流构建消息
- 用 Pydantic schema 请求结构化输出

## 前置要求

- 完成 Tutorial 01
- 理解 async/await 基础

## 核心概念

### 消息 (Msg)

`Msg` 是 Agent 之间通信的基本单位。每条消息包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | 唯一标识符 |
| `name` | `str` | 发送者名称 |
| `role` | `"user" / "assistant" / "system"` | 发送者角色 |
| `content` | `list[ContentBlock]` | 内容块列表 |
| `metadata` | `dict` | 任意键值对元数据 |
| `created_at` | `str` | ISO 8601 创建时间 |
| `finished_at` | `str \| None` | ISO 8601 完成时间 |
| `usage` | `Usage \| None` | Token 使用量 |
| `finished_reason` | `ReplyFinishedReason \| None` | 正常完成、中断、超出迭代上限或错误 |
| `structured_output` | `dict \| None` | 请求结构化输出时的校验结果 |
| `error` | `ErrorInfo \| None` | 回复因错误结束时的结构化错误 |

### 六种 ContentBlock

消息的 `content` 是一个内容块列表。每种块有不同的角色约束：

| Block 类型 | 说明 | 允许的角色 |
|-----------|------|-----------|
| `TextBlock` | 文本内容 | user, assistant, system |
| `DataBlock` | 二进制数据（图片/音频等） | user, assistant |
| `ThinkingBlock` | 思维链推理过程 | assistant |
| `ToolCallBlock` | 工具调用请求 | assistant |
| `ToolResultBlock` | 工具执行结果 | assistant |
| `HintBlock` | Agent 内部指导提示 | assistant |

角色约束在构造时强制验证：
- **user** 消息只能包含 `TextBlock` 和 `DataBlock`
- **system** 消息只能包含 `TextBlock`
- **assistant** 消息可以包含所有类型

### 事件 (Event)

Event 是消息的流式视图。Agent 执行过程中会产生一系列事件，这些事件最终组成一条完整的助手消息。

**核心原则**：一次 `reply` 调用 = 一条助手消息 = 一个事件流

文本、思考、数据、工具调用和工具结果等**分块内容**遵循
**start → delta → end** 模式；`HINT_BLOCK`、确认、中断和 `CUSTOM`
等控制事件是一次性事件，不应等待配对的 start/end：

```
ReplyStartEvent
  ├── ModelCallStartEvent
  │     ├── ThinkingBlockStartEvent → ThinkingBlockDeltaEvent... → ThinkingBlockEndEvent
  │     ├── TextBlockStartEvent → TextBlockDeltaEvent... → TextBlockEndEvent
  │     ├── DataBlockStartEvent → DataBlockDeltaEvent... → DataBlockEndEvent
  │     └── ToolCallStartEvent → ToolCallDeltaEvent... → ToolCallEndEvent
  │   ModelCallEndEvent
  │
  ├── ToolResultStartEvent → ToolResultTextDeltaEvent... → ToolResultEndEvent
  ├── HintBlockEvent（一次性运行时提示）
  ├── RequireUserConfirmEvent / RequireExternalExecutionEvent（一次性暂停事件）
  │
  └── (下一轮推理-执行循环...)
ReplyEndEvent
```

处理事件时应对未知类型做安全降级。这样服务端增加一次性事件后，旧 UI 仍能继续
显示文本和结束状态。

### 消息-事件对偶性

事件流可以用 `msg.append_event(event)` 逐步重建完整消息。这是 AgentScope 前后端分离的基础：后端流式推送事件，前端实时重建消息。

```python
msg = None
async for event in agent.reply_stream(user_msg):
    if event.type == EventType.REPLY_START:
        msg = AssistantMsg(
            name=event.name,
            content=[],
            id=event.reply_id,
        )
    if msg is not None:
        msg.append_event(event)

assert msg is not None
# msg 现在包含完整的助手回复
```

Web 前端不需要自己重复实现聚合规则。TypeScript 包
`@agentscope-ai/agentscope` 提供同样的 `appendEvent`：

```typescript
import { EventType } from "@agentscope-ai/agentscope/event";
import {
  appendEvent,
  AssistantMsg,
} from "@agentscope-ai/agentscope/message";

if (event.type === EventType.REPLY_START) {
  current = AssistantMsg({
    id: event.reply_id,
    name: event.name,
    content: [],
  });
} else if (current) {
  appendEvent(current, event);
}
```

### 结构化输出

当后续代码需要消费固定字段，而不是解析自然语言时，把 Pydantic 模型传给
`structured_schema`：

```python
class SalesInsight(BaseModel):
    metric: str
    value: float
    explanation: str

result = await agent.reply(
    user_msg,
    structured_schema=SalesInsight,
)
print(result.structured_output)
```

流式场景需要同时拿到事件和最终结构化结果时，使用
`reply_stream(..., structured_schema=..., yield_final_msg=True)`；最后一个
`Msg` 的 `structured_output` 包含校验后的字典。

## 示例：探索 DataMuse 的消息和事件

本期示例让 DataMuse 回答数据分析问题，我们在客户端侧：
1. 逐一观察每种事件类型
2. 用 `append_event()` 从事件流重建消息
3. 对比流式事件和最终消息的内容
4. 用 Pydantic schema 获取可直接供代码消费的结果

## 运行示例

```bash
cd tutorials/02_message_and_event
python main.py
```

## 进一步探索

- 观察不同模型（如支持 thinking 的模型）会产生哪些不同的事件
- 尝试给 Agent 添加工具，观察 ToolCall / ToolResult 事件
- 尝试构造一个包含 `DataBlock`（图片）的 UserMsg

## 下一期预告

**Tutorial 03: Tool 系统** — 赋予 DataMuse 读写文件、执行脚本的能力，让它真正能分析数据。
