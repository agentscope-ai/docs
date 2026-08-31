# Tutorial 16: Complete DataMuse — 最终整合

本章把 T01-T12 中适合放进单体应用的核心模块合成一个可运行的 DataMuse：它会读取同一份销售数据，做数据概览和维度拆解，在写入报告前触发确认事件，并把最终 Markdown 报告保存到本地 workspace 中。

> **什么时候需要这个？** 你学完本地 Agent 的核心模块后，想看一个端到端、最小但完整的应用如何组装出来——既能在命令行里跑流程，也能在浏览器里跑流式对话。

## 本章基于前序章节

- **T01 — Agent / Model**：DataMuse 的推理主体
- **T02 — Event 流**：`reply_stream` 推送的事件，前端用来实时渲染
- **T03 — 自定义 `ToolBase`**：本章的 `SalesProfile` / `SalesBreakdown` / `ReportWriter`
- **T07 — Permission ASK 行为**：读数据自动 ALLOW，写报告触发 ASK
- **T08 — `UserConfirmResultEvent`**：把前端用户的确认结果送回 Agent
- **T09 — 流式 UI 渲染**：Web UI 复用 T09 的事件分发思路
- **T10 — `ContextConfig.tool_result_limit`**：截断过长的工具结果
- **T11 — Middleware**：`TimingMiddleware` 记录每轮耗时
- **T12 — `LocalWorkspace`**：作为报告的落地空间和 Offloader

T13-T15 是同一业务案例的另外两条扩展路径，不是本章必须嵌入的运行时：T13-T14 把 DataMuse 变成多用户服务和定时任务，T15 在确有必要时把单 Agent 展开成团队。本章选择保留一个容易读、容易跑的自包含应用。

## 你将学到

- 如何把自定义分析工具组织成一个完整 Data Agent
- 如何在一个入口里同时使用事件流、权限确认、ContextConfig、Middleware 和 LocalWorkspace
- 如何把"分析过程"和"分析产物"都落到同一个工作区
- 如何用一个极简的 FastAPI + HTML 构建浏览器交互界面
- 如何从教程 demo 过渡到可复用的应用骨架

## 前置要求

- 建议完成 Tutorial 01-12
- T13-T15 可选：用于理解服务化、调度和团队化扩展
- Python 3.12
- 安装 AgentScope：`pip install agentscope==2.0.4`
- 准备好 `tutorials/data/sales_data.csv`
- 设置 `DASHSCOPE_API_KEY` 或 `OPENAI_API_KEY`

## 两种运行模式

### 模式 A：命令行 Demo

最快的方式，直接在终端跑完整流程：

```bash
cd tutorials/16_complete_datamuse
python main.py
```

运行后会看到：

1. DataMuse 先调用 `SalesProfile` 检查数据结构和样例。
2. 再调用 `SalesBreakdown` 分别按 category、region、payment_method、customer_tier 做拆解。
3. 当它准备调用 `ReportWriter` 写报告时，事件流会出现 `REQUIRE_USER_CONFIRM`。
4. 本教程为了开箱即用会自动确认；真实场景中可以由用户手动确认。
5. 报告会写入 `workspace/reports/`。

### 模式 B：浏览器 Web UI

用浏览器交互，体验流式输出 + 权限确认弹窗。无需 Redis 或 Node.js：

```bash
cd tutorials/16_complete_datamuse
pip install uvicorn fastapi
python serve.py
```

打开 http://localhost:8000，你会看到一个简洁的对话界面。试试输入：

```
Analyze sales by category and region, then write a report.
```

Web UI 会实时展示：
- 流式文本生成
- 工具调用卡片（名称 + 参数）
- 工具执行结果
- **权限确认弹窗**（ReportWriter 写文件时触发，你可以选择 Allow 或 Deny）

```
┌─────────────────────────────────────────────┐
│  DataMuse - Sales Analyst          [header] │
├─────────────────────────────────────────────┤
│                                             │
│  [user message]         ────► 右对齐蓝色气泡│
│                                             │
│  [tool call card]       ────► 工具名 + 参数 │
│  [tool result]          ────► 执行结果摘要  │
│                                             │
│  ┌─ Permission Required ──────────────┐     │
│  │  ReportWriter                      │     │
│  │  {"title": "...", "markdown": ...} │     │
│  │  [Allow]  [Deny]                   │     │
│  └────────────────────────────────────┘     │
│                                             │
│  [assistant response]   ────► 左对齐白色气泡│
│                                             │
├─────────────────────────────────────────────┤
│  [input box]                       [Send]   │
└─────────────────────────────────────────────┘
```

## 技术实现

### serve.py 做了什么

这里的 `/chat` 是本章轻量 Web UI 自己定义的端点；如果使用 T13 的 Agent Service，事件流入口是 `/sessions/{id}/stream`。

```python
# 1. 复用 main.py 的自定义工具 (SalesProfile, SalesBreakdown, ReportWriter)
# 2. 极简 FastAPI：两个端点
#    POST /chat    → SSE 流式推送 AgentEvent
#    POST /confirm → 接收前端的确认/拒绝结果

@app.post("/chat")
async def chat(req: ChatRequest):
    async def event_stream():
        async for event in agent.reply_stream(msg):
            yield f"data: {json.dumps(event.model_dump())}\n\n"
            if event.type == EventType.REQUIRE_USER_CONFIRM:
                # 暂停，等待前端调用 /confirm
                await pending_confirm.wait()
                # 继续流式处理
                async for e in agent.reply_stream(confirm_result):
                    yield f"data: {json.dumps(e.model_dump())}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

### index.html 做了什么

```javascript
// 1. fetch('/chat', {method: 'POST', body: ...})
// 2. 逐行解析 SSE: "data: {...}\n\n"
// 3. 根据 event.type 分发渲染:
//    TEXT_BLOCK_DELTA → 追加文本到气泡
//    TOOL_CALL_*     → 渲染工具卡片
//    TOOL_RESULT_*   → 渲染结果框
//    REQUIRE_USER_CONFIRM → 弹出确认卡片
// 4. 用户点击 Allow/Deny → POST /confirm → 流继续
```

## 模块串联

| 模块 | 本章中的作用 |
|---|---|
| Agent / Model | 构建 DataMuse 的推理入口 |
| Message / Event | `reply_stream` 产生事件流，SSE 推送到前端 |
| Toolkit / ToolBase | `SalesProfile`、`SalesBreakdown`、`ReportWriter` |
| Permission | 读数据自动允许（ALLOW），写报告触发确认（ASK） |
| Context | `tool_result_limit=1200` 截断过长结果 |
| Middleware | `TimingMiddleware` 记录每轮耗时 |
| Workspace | `LocalWorkspace` 保存报告并支持 offload |

### 哪些能力没有硬塞进本章

| 能力 | 本章选择 | 对应章节 |
|---|---|---|
| MCP / Skill | 分析工具已经是本地 Python Tool，不额外增加远程依赖或操作手册 | T05-T06 |
| Agent Service / Schedule | 保持单用户、单进程示例，服务化版本单独运行 | T13-T14 |
| Multi-Agent | 当前任务一个 Agent 足够，避免不必要的角色通信 | T15 |

“完整”在这里指业务闭环完整：有输入、分析、权限边界、过程反馈和落地产物；不表示一个进程必须同时启用 AgentScope 的每一项能力。

## 文件结构

```
16_complete_datamuse/
├── README.md         ← 你在读的文档
├── main.py           ← 模式 A：命令行 Demo
├── serve.py          ← 模式 B：FastAPI + SSE 服务
├── index.html        ← 模式 B：单文件前端
└── workspace/        ← 运行后生成
    └── reports/
```

## 为什么这是最终章

前面的章节分别讲概念和 API，本章回答"学完以后能不能搭出一个 Data Agent"。它不是新的抽象，也不是把每种架构堆到一起，而是把 DataMuse 收束成一个能跑的最小完整应用：有数据输入、有分析工具、有权限边界、有运行过程、有最终产物。

- **模式 A** 展示所有核心模块如何在一个脚本里协作
- **模式 B** 展示如何用最少代码（一个 serve.py + 一个 HTML）把 Agent 暴露为 Web 应用
