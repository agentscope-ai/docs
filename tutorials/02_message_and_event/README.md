# Tutorial 02: Message & Event — Agent 的通信协议

> **什么时候需要这个？** 你要做 UI、做日志、做调试，需要看清 Agent 内部到底发生了什么；或者你想理解 `reply_stream()` 返回的事件长什么样、怎么从事件流重建一条消息。后面所有"流式 UI / 中间件 / 服务" 都依赖你看懂这套协议。

## 本章基于前序章节

- **T01 — Agent 与 `reply_stream`**：本章在 T01 的最小 Agent 之上，深入看它产出的事件流和最终消息。

## 你将学到

- `Msg` 消息的完整结构和六种 ContentBlock
- Event 事件系统的生命周期模式（start → delta → end）
- 消息-事件对偶性：事件流如何重建完整消息
- 用 `append_event()` 从事件流构建消息

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

多数流式内容块遵循 **start → delta → end** 的生命周期模式；
`HintBlockEvent` 是一次性事件，不拆分为 start / delta / end：

```
ReplyStartEvent
  ├── ModelCallStartEvent
  │     ├── ThinkingBlockStartEvent → ThinkingBlockDeltaEvent... → ThinkingBlockEndEvent
  │     ├── TextBlockStartEvent → TextBlockDeltaEvent... → TextBlockEndEvent
  │     └── ToolCallStartEvent → ToolCallDeltaEvent... → ToolCallEndEvent
  │   ModelCallEndEvent
  │
  ├── ToolResultStartEvent → ToolResultTextDeltaEvent... → ToolResultEndEvent
  │
  ├── HintBlockEvent（一次性提示）
  │
  └── (下一轮推理-执行循环...)
ReplyEndEvent
```

### 消息-事件对偶性

事件流可以用 `msg.append_event(event)` 逐步重建完整消息。这是 AgentScope 前后端分离的基础：后端流式推送事件，前端实时重建消息。

```python
msg = AssistantMsg(name="agent", content=[], id=event.reply_id)
async for event in agent.reply_stream(user_msg):
    msg.append_event(event)
# msg 现在包含完整的助手回复
```

浏览器或 Node.js 客户端可以使用 TypeScript 包
`@agentscope-ai/agentscope` 完成同样的重建：

```bash
npm install @agentscope-ai/agentscope@0.0.13
```

```typescript
import { EventType } from "@agentscope-ai/agentscope/event";
import {
  appendEvent,
  AssistantMsg,
} from "@agentscope-ai/agentscope/message";

let reply;

for await (const event of eventStream) {
  if (event.type === EventType.REPLY_START) {
    reply = AssistantMsg({
      id: event.reply_id,
      name: event.name,
      content: [],
    });
  }

  if (reply) {
    appendEvent(reply, event);
  }
}
```

## 示例：探索 DataMuse 的消息和事件

本期示例让 DataMuse 回答数据分析问题，我们在客户端侧：
1. 逐一观察每种事件类型
2. 用 `append_event()` 从事件流重建消息
3. 对比流式事件和最终消息的内容

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
