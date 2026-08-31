# Tutorial 09: 流式 UI — 构建实时交互界面

> **什么时候需要这个？** 你要做真正的实时交互界面（终端 TUI、Web 聊天等），需要把文本、多模态数据、思考过程、工具调用、token 统计和 HITL 确认组织成一套连贯的视觉体验。

## 本章基于前序章节

- **T02 — Event 系统全景与 `start → delta → end` 模式**：本章把 T02 介绍的事件类型扩展成完整的 UI 渲染方案。
- **T03 — `TOOL_CALL_*` / `TOOL_RESULT_*` 事件**：UI 里"工具卡片"和"结果摘要"的数据来源。
- **T08 — `REQUIRE_USER_CONFIRM` / `REQUIRE_EXTERNAL_EXECUTION`**：在 UI 中如何整合 HITL 事件。

## 你将学到

- Event 类型全景及其 start → delta → end 生命周期
- `reply_id` 和 `block_id` 的关联关系
- Token 用量追踪（`ModelCallEndEvent`）
- 如何用事件分发构建一个功能丰富的终端 UI
- HITL 事件在 UI 中的整合处理

## 前置要求

- 完成 Tutorial 08
- 理解 Event 系统（Tutorial 02 回顾）

## 核心概念

### Event 类型全景

AgentScope 的事件系统涵盖 Agent 执行的每个阶段：

```
Reply 级别
├─ REPLY_START          ── 回复开始（包含 session_id, reply_id, name）
└─ REPLY_END            ── 回复结束

Model 调用
├─ MODEL_CALL_START     ── 模型调用开始（model_name）
└─ MODEL_CALL_END       ── 模型调用结束（input_tokens, output_tokens）

文本块
├─ TEXT_BLOCK_START      ── 文本开始（block_id）
├─ TEXT_BLOCK_DELTA      ── 文本增量（delta）
└─ TEXT_BLOCK_END        ── 文本结束

数据块
├─ DATA_BLOCK_START      ── 图片、音频等数据开始（media_type）
├─ DATA_BLOCK_DELTA      ── base64 数据增量
└─ DATA_BLOCK_END        ── 数据结束

思考块
├─ THINKING_BLOCK_START  ── 思考开始
├─ THINKING_BLOCK_DELTA  ── 思考增量
└─ THINKING_BLOCK_END    ── 思考结束

一次性提示
└─ HINT_BLOCK            ── Team 消息、后台结果等完整提示

工具调用
├─ TOOL_CALL_START       ── 开始调用（tool_call_name）
├─ TOOL_CALL_DELTA       ── 参数增量（JSON 片段）
└─ TOOL_CALL_END         ── 调用结束

工具结果
├─ TOOL_RESULT_START      ── 结果开始
├─ TOOL_RESULT_TEXT_DELTA ── 文本结果增量
├─ TOOL_RESULT_DATA_DELTA ── 二进制数据增量
└─ TOOL_RESULT_END        ── 结果结束（state: success/error/denied）

HITL 事件
├─ REQUIRE_USER_CONFIRM        ── 需要用户确认
├─ REQUIRE_EXTERNAL_EXECUTION  ── 需要外部执行
├─ USER_CONFIRM_RESULT         ── 用户确认结果
├─ EXTERNAL_EXECUTION_RESULT   ── 外部执行结果
└─ USER_INTERRUPT              ── 用户中止一个等待恢复的回复

其他
├─ EXCEED_MAX_ITERS    ── 超过最大迭代次数
└─ CUSTOM              ── 服务或应用自定义的扩展事件
```

`USER_CONFIRM_RESULT`、`EXTERNAL_EXECUTION_RESULT` 和 `USER_INTERRUPT` 通常是 UI 传回 `reply_stream()`、用于恢复或中止 parked reply 的输入事件，不一定会出现在一次普通回复的输出流里。UI 仍应认识它们，并对未知 `CUSTOM.name` 或未来新增事件做安全降级。

### Token 用量追踪

`ModelCallEndEvent` 包含 token 使用信息：

```python
case EventType.MODEL_CALL_END:
    print(f"Input: {event.input_tokens}, Output: {event.output_tokens}")
```

累计多次模型调用的 token，可以用于成本估算。

### UI 设计模式

流式 UI 的核心是**事件分发 + 状态管理**：

```python
total_input_tokens = 0
total_output_tokens = 0

async for event in agent.reply_stream(msg):
    match event.type:
        case EventType.REPLY_START:
            # 初始化 UI 状态
        case EventType.TEXT_BLOCK_DELTA:
            # 实时渲染文本
        case EventType.THINKING_BLOCK_DELTA:
            # 折叠显示思考过程
        case EventType.TOOL_CALL_START:
            # 显示工具调用指示器
        case EventType.TOOL_RESULT_END:
            # 显示执行结果摘要
        case EventType.MODEL_CALL_END:
            # 累计 token 用量
            total_input_tokens += event.input_tokens
            total_output_tokens += event.output_tokens
        case EventType.REPLY_END:
            # 显示最终统计
```

## 示例：终端流式 UI

本期实现一个完整的终端 UI，展示：

1. 实时流式文本输出
2. 思考过程（带前缀标识）
3. 工具调用进度指示
4. 工具结果摘要
5. Token 用量统计
6. 多轮 ReAct 循环的可视化

## 运行示例

```bash
cd tutorials/09_streaming_ui
python main.py
```

## 进一步探索

- 用 `rich` 库替换 print，实现彩色输出和进度条
- 添加工具结果的折叠/展开功能
- 统计每次模型调用的耗时（利用 `MODEL_CALL_START` 和 `MODEL_CALL_END` 的时间差）
- 将 HITL 事件集成到 UI 中，实现交互式确认

## 下一期预告

**Tutorial 10: Context 管理** — 处理长对话和大工具结果，配置上下文压缩策略。
