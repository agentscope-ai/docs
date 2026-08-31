# Tutorial 10: Context 管理 — 长对话与大结果处理

> **什么时候需要这个？** 对话变长、工具一次返回的结果很大（比如 `query_sales` 拉了几千行 CSV），token 数量逼近上下文上限——这时你需要自动压缩历史、截断大工具结果，或把它们 offload 到外部存储。

## 本章基于前序章节

- **T02 — `Msg` 结构**：理解被压缩的对象长什么样。
- **T03 — `ToolResultBlock`**：`tool_result_limit` 截断的就是它。
- **T07 — `PermissionMode.DONT_ASK`** 等长跑场景：长对话和定时任务最先撞上上下文上限。

## 你将学到

- 上下文窗口的挑战及其解决方案
- `ContextConfig` 的三个关键参数
- 自动压缩流程：分割 → 摘要 → 保留近期
- 工具结果截断：超长结果自动裁剪
- `compress_context()` 手动触发压缩，并用 `instructions` 给压缩器提示

## 前置要求

- 完成 Tutorial 09
- 理解 Agent 的消息上下文结构

## 核心概念

### 上下文窗口的挑战

Agent 在多轮对话 + 大量工具调用后，上下文会迅速膨胀：

- 每轮对话的输入/输出消息
- 工具调用的参数和返回结果（可能很大）
- 思考过程的内容

当上下文接近模型的最大 token 限制时，就需要压缩或裁剪。

### ContextConfig

```python
from agentscope.agent import Agent
from agentscope.agent import ContextConfig

agent = Agent(
    ...,
    context_config=ContextConfig(
        trigger_ratio=0.8,       # 触发压缩的阈值（占最大上下文比例）
        reserve_ratio=0.1,       # 压缩后保留的最近消息比例
        tool_result_limit=50000, # 单个工具结果的最大 token 数
    ),
)
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `trigger_ratio` | 0.8 | 当 token 数超过 `context_size × trigger_ratio` 时触发压缩 |
| `reserve_ratio` | 0.1 | 压缩后保留最近的消息（占总上下文的比例） |
| `tool_result_limit` | 50000 | 单个工具结果超过此 token 数时自动截断 |

### 自动压缩流程

```
Agent 准备新一轮推理
  ↓
估算当前 token 数
  ↓ 未超阈值 → 跳过
  ↓ 超过 trigger_ratio
分割上下文：[旧消息 | 近期消息]
  ↓
对旧消息生成结构化摘要
  ↓
摘要内容：
  - task_overview: 用户请求和目标
  - current_state: 已完成的工作
  - important_discoveries: 关键发现
  - next_steps: 下一步计划
  - context_to_preserve: 需要保留的上下文
  ↓
用摘要替换旧消息，保留近期消息
```

### 工具结果截断

当工具返回的结果超过 `tool_result_limit` 个 token 时，AgentScope 会自动截断结果。这防止单个工具结果占用过多上下文。

### 手动压缩

```python
from agentscope.message import HintBlock

# 使用默认配置压缩
await agent.compress_context()

# 使用自定义配置压缩
custom_config = ContextConfig(
    trigger_ratio=0.5,    # 更低的阈值
    reserve_ratio=0.2,    # 保留更多近期消息
)
await agent.compress_context(context_config=custom_config)

# 给压缩器额外提示：哪些业务细节必须保留
await agent.compress_context(
    instructions=HintBlock(
        hint="Preserve the user's preferred report format and KPI formulas.",
    ),
)
```

`instructions` 不会改变 Agent 的长期系统提示，只会影响这一次压缩摘要的取舍。比如 DataMuse 已经和用户约定了"日报必须包含 GMV、订单数、客单价"，就可以在手动压缩时把这个约定钉住。

### Offloader 协议

在 Agent Service 场景下，`Offloader` 将被压缩的上下文和截断的工具结果持久化到工作空间：

```python
class Offloader(Protocol):
    async def offload_context(
        self, session_id: str, msgs: list[Msg],
    ) -> str: ...

    async def offload_tool_result(
        self, session_id: str, tool_result: ToolResultBlock,
    ) -> str: ...
```

这允许 Agent 在需要时重新加载完整的历史记录。

## 示例：长对话上下文管理

本期通过多轮数据分析对话演示：

1. 不同 `ContextConfig` 参数的效果
2. 工具结果截断的行为
3. 手动触发压缩并观察摘要生成

## 运行示例

```bash
cd tutorials/10_context_management
python main.py
```

## 进一步探索

- 调整 `trigger_ratio` 和 `reserve_ratio`，观察压缩时机和保留量的变化
- 降低 `tool_result_limit`，观察大工具结果的截断行为
- 进行 20+ 轮对话，触发自动压缩
- 自定义 `compression_prompt` 和 `summary_template`
- 写一个 Middleware 实现 `on_compress_context`，在压缩前自动补充业务保留规则

## 下一期预告

**Tutorial 11: Middleware** — 用中间件实现日志、计时、动态提示等横切关注点。
