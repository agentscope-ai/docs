# Tutorial 11: Middleware — 可插拔的行为扩展

> **什么时候需要这个？** 你想加日志、计时、token 计费、tracing、动态注入 prompt 这些"横切关注点"——但不想把它们硬编码进 Agent 主代码。Middleware 让你在 ReAct 循环的关键节点钉钉子，而 Agent 本身保持干净。

## 本章基于前序章节

- **T01 — Agent ReAct 循环（reasoning + acting）**：Middleware 的执行 Hook 对应 ReAct 循环的不同阶段。
- **T02 — Event 流**：洋葱模型的 hook 会拦截、转发或加工事件流。
- **T09 — Token 统计 / `MODEL_CALL_END`**：本章的 `CostTrackerMiddleware` 在 T09 手写统计的基础上抽象成中间件。

## 你将学到

- Middleware Hook 位置及其作用
- 洋葱模型（Onion）vs 变换器模型（Transformer）
- 自定义中间件开发
- 内置 `TracingMiddleware` 的使用
- `on_compress_context` 与 `list_tools()` 的作用边界
- 多中间件的执行顺序

## 前置要求

- 完成 Tutorial 10
- 理解 Agent 的 ReAct 循环（reasoning + acting）

## 核心概念

### Middleware 系统概述

中间件允许你在 Agent 执行的关键节点插入自定义逻辑，而不修改 Agent 本身的代码。这是典型的横切关注点（Cross-cutting Concerns）处理方式。

### Hook 位置

```
Agent.reply()
│
├─ on_reply          ── 拦截整个回复过程（最外层）
│   │
│   ├─ on_reasoning  ── 拦截推理阶段（模型调用 + 解析）
│   │   │
│   │   └─ on_model_call ── 拦截原始模型 API 调用
│   │
│   └─ on_acting     ── 拦截工具执行
│
└─ on_system_prompt  ── 变换系统提示（独立管线）

Agent.compress_context()
│
└─ on_compress_context ── 拦截上下文压缩

Middleware.list_tools()
└─ 返回这个 middleware 额外提供的工具（不是 hook）
```

| Hook | 模式 | 说明 |
|------|------|------|
| `on_reply` | 洋葱 | 拦截整个回复，包含所有 ReAct 循环 |
| `on_reasoning` | 洋葱 | 拦截推理阶段（每个 ReAct 迭代） |
| `on_acting` | 洋葱 | 拦截工具执行 |
| `on_model_call` | 洋葱 | 拦截模型 API 调用 |
| `on_compress_context` | 洋葱 | 拦截 `compress_context()`，适合补压缩提示、记录压缩日志 |
| `on_system_prompt` | 变换器 | 顺序变换系统提示字符串 |
| `list_tools()` | 工具发现 | 让 middleware 暴露额外工具；库模式要手动放进 `Toolkit`，Agent Service 会在组装 toolkit 时收集 |

### 洋葱模型 vs 变换器模型

**洋葱模型**（on_reply, on_reasoning, on_acting, on_model_call, on_compress_context）：

```python
class MyMiddleware(MiddlewareBase):
    async def on_reasoning(self, agent, input_kwargs, next_handler):
        # Before: 在推理前执行
        print("Before reasoning")
        async for event in next_handler(**input_kwargs):
            yield event  # 中间：转发事件
        # After: 在推理后执行
        print("After reasoning")
```

多个中间件形成嵌套层：
```
Middleware A (before) → Middleware B (before) → 核心逻辑
                                              ↓
Middleware A (after)  ← Middleware B (after)  ← 返回
```

**变换器模型**（on_system_prompt）：

```python
class TimeInjector(MiddlewareBase):
    async def on_system_prompt(self, agent, current_prompt):
        return current_prompt + f"\nCurrent time: {datetime.now()}"
```

顺序管线，每个中间件接收前一个的输出。

### 自定义中间件

继承 `MiddlewareBase`，只实现你需要的 hook：

```python
from agentscope.middleware import MiddlewareBase

class LoggingMiddleware(MiddlewareBase):
    async def on_reply(self, agent, input_kwargs, next_handler):
        print(f"[{agent.name}] Reply started")
        async for event in next_handler(**input_kwargs):
            yield event
        print(f"[{agent.name}] Reply ended")
```

### 注册中间件

```python
agent = Agent(
    ...,
    middlewares=[
        LoggingMiddleware(),
        TimingMiddleware(),
        TracingMiddleware(),
    ],
)
```

中间件按列表顺序形成洋葱层：第一个是最外层，最后一个最接近核心逻辑。

### 内置 TracingMiddleware

`TracingMiddleware` 提供 OpenTelemetry 集成，自动为 reply、model call、tool execution 创建 span：

```python
from agentscope.middleware import TracingMiddleware

agent = Agent(
    ...,
    middlewares=[TracingMiddleware()],
)
```

当未配置 tracing 时，`TracingMiddleware` 零开销直通。

### 常见内置 Middleware

| Middleware | 什么时候用 |
|------------|------------|
| `TracingMiddleware` | 需要 OpenTelemetry tracing、排查慢调用 |
| `ReplyBudgetControlMiddleware` | 需要给单次回复设 token 预算，超预算就收尾 |
| `RAGMiddleware` | 需要从 Knowledge Base 检索资料并注入上下文 |
| `TTSMiddleware` | 需要把文本回复转成音频事件 |
| `AgenticMemoryMiddleware` / `Mem0Middleware` / `ReMeMiddleware` | 需要长期记忆，跨会话保留用户偏好或事实 |

## 示例：为 DataMuse 添加中间件

本期实现四个自定义中间件：

1. **LoggingMiddleware** — 记录 reply 开始/结束
2. **TimingMiddleware** — 测量模型调用耗时
3. **CostTrackerMiddleware** — 累计 token 消费
4. **DynamicPromptMiddleware** — 注入当前时间到系统提示
5. **CompressionHintMiddleware** — 在上下文压缩前补充保留提示

## 运行示例

```bash
cd tutorials/11_middleware
python main.py
```

## 进一步探索

- 实现一个 `RateLimitMiddleware`，限制模型调用频率
- 在 `on_acting` 中实现工具结果缓存
- 组合多个中间件，观察洋葱嵌套的执行顺序
- 配置 `TracingMiddleware` + Jaeger，可视化追踪链路
- 用 `list_tools()` 给 RAG 或长期记忆 middleware 暴露搜索工具

## 下一期预告

**Tutorial 12: Workspace** — 理解 Agent 的统一工作空间：内置工具注入、MCP/Skill 管理、Offloader。
