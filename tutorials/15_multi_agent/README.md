# Tutorial 15: Multi-Agent — 多 Agent 协作

> **什么时候需要这个？** 单 Agent 的工具太多导致上下文撑爆、LLM 选错工具，或者任务可以清晰拆成几个角色（采集 / 分析 / 写报告）。多 Agent 协作让每个 Agent 只关心自己那一摊；库模式下用 Python 编排，服务模式下也可以交给 Team tools 编排。

## 本章基于前序章节

- **T01 — Agent / `reply` / `reply_stream`**：每个角色都是一个独立 Agent 实例。
- **T03 — 工具系统**：不同角色配不同工具集（Collector 配 `query_sales`，Writer 配 `Bash` 写文件等）。
- **T02 — `Msg`**：Agent 之间通过传递消息接力，`observe()` 用来注入背景但不触发推理。

## 你将学到

- AgentScope 2.0 的多 Agent 设计思路
- `observe()` 方法：无推理的消息注入
- 多 Agent 编排模式：串行、并行、动态路由
- Agent 间的消息传递和结果接力
- Python 编排与 Agent Service Team tools 的边界

## 前置要求

- 完成 Tutorial 01-14
- 理解 Agent 的 reply、reply_stream、observe API

## 核心概念

### 为什么需要多 Agent？

单个 Agent 虽然能力强大，但在复杂任务中会遇到瓶颈：

- **上下文爆炸**：同时处理数据采集、分析、可视化时，上下文迅速膨胀
- **工具冲突**：太多工具让 LLM 选择困难
- **职责不清**：一个 Agent 同时承担多个角色效率低

多 Agent 的解决方案：每个 Agent 专注一个职责，通过编排逻辑协作。

但“任务有多个步骤”本身不是拆分理由。默认先用一个 Agent 加清晰工具完成任务；只有至少出现下面一种情况时，再考虑 Multi-Agent：

- 不同角色需要明显不同的工具、权限或系统提示
- 某些子任务可以并行，且并行收益足以覆盖通信成本
- 单 Agent 的工具 Schema 或上下文已经过大，影响选择和推理稳定性
- 业务上需要独立的责任边界，例如采集结果必须交给另一个角色审核

如果多个角色只是顺序复述同一份上下文，拆分通常只会增加模型调用、延迟和调试难度。

### AgentScope 的多 Agent 设计

AgentScope 2.0 的库模式不强制你使用某个"编排框架"——它提供**消息传递原语**，让你用 Python 代码实现编排：

```python
# Agent 之间通过消息传递协作
result = await agent_a.reply(user_msg)        # A 处理
await agent_b.observe(result)                  # B 接收 A 的结果（不触发推理）
final = await agent_b.reply(follow_up_msg)    # B 基于上下文推理
```

### observe() vs reply()

| 方法 | 行为 | 用途 |
|------|------|------|
| `reply(msg)` | 接收消息 → 触发推理 → 返回回复 | 需要 Agent 思考和行动 |
| `observe(msg)` | 接收消息 → 仅存入上下文 | 提供背景信息，不触发推理 |

`observe()` 是多 Agent 协作的关键：它让 Agent 获得上下文信息，而不需要立即响应。

### 库模式 vs 服务模式

| 模式 | 核心机制 | 什么时候用 |
|------|----------|------------|
| Python 编排 | `reply()` / `observe()` / `asyncio.gather()` | 单脚本、Notebook、你希望业务代码明确控制流程 |
| Agent Service Team | `TeamCreate` / `AgentCreate` / `AgentInvite` / `TeamSay` | 多用户服务、需要 leader agent 动态创建或邀请 worker |

本章主线仍然使用 Python 编排，因为它最透明，方便学生看清 Agent 之间怎么传递上下文。T13 的 Agent Service 已经内置 Team tools；如果你把多 Agent 放到服务端，leader session 会拿到 `TeamCreate`、`AgentCreate`、`TeamSay` 等工具，worker 通过 `TeamSay` 汇报结果。

### 三种编排模式

#### 1. 串行流水线

```
User → Agent A → Agent B → Agent C → Result
          │          │          │
       采集数据    分析数据    生成报告
```

```python
data = await collector.reply(user_msg)
await analyst.observe(data)
analysis = await analyst.reply(analyze_msg)
await writer.observe(analysis)
report = await writer.reply(write_msg)
```

#### 2. 并行分支

```
                ┌→ Agent B (分析 A) ─┐
User → Agent A ─┤                    ├→ Agent D (汇总)
                └→ Agent C (分析 B) ─┘
```

```python
data = await collector.reply(user_msg)
await analyst_a.observe(data)
await analyst_b.observe(data)
result_a, result_b = await asyncio.gather(
    analyst_a.reply(task_a_msg),
    analyst_b.reply(task_b_msg),
)
await summarizer.observe(result_a)
await summarizer.observe(result_b)
summary = await summarizer.reply(summarize_msg)
```

#### 3. 动态路由

```
User → Router Agent ──┬→ Agent A (简单任务)
                      ├→ Agent B (复杂任务)
                      └→ Agent C (特殊任务)
```

```python
routing = await router.reply(user_msg)
route = parse_route(routing)

if route == "simple":
    result = await simple_agent.reply(user_msg)
elif route == "complex":
    result = await complex_agent.reply(user_msg)
```

## 示例：DataMuse 团队

本期把 DataMuse 展开为一个**可选的团队化形态**，创建三个角色：

1. **DataMuse_Collector** — 数据采集员，配备 Read、Glob、query_sales 工具
2. **DataMuse_Analyst** — 数据分析师，配备 SalesSummary 和 Bash 工具
3. **DataMuse_Writer** — 报告撰写员，配备 Bash 工具（用于写文件）

编排流程：用户提出分析需求 → Collector 采集 → Analyst 分析 → Writer 出报告

## 运行示例

```bash
cd tutorials/15_multi_agent
python main.py
```

## 进一步探索

- 实现并行分析：让 RegionAnalyst 和 CategoryAnalyst 同时工作
- 添加动态路由：根据用户请求复杂度选择不同的处理流程
- 创建一个"审核员" Agent，检查报告质量并决定是否需要重新分析
- 用 Middleware 实现 Agent 间通信的日志追踪
- 在 Agent Service 中用 `TeamCreate` + `AgentCreate` 复刻本章流水线

## 下一期预告

**Tutorial 16: Complete DataMuse** — 回到一个自包含应用，把核心模块组装成可运行的命令行和轻量 Web 版本。T15 的团队化方案是扩展路径，不是 T16 的必选依赖。
