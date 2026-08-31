# AgentScope 2.0 Tutorial Series

> **DataMuse** — 一个从零到可部署的智能数据分析助手

本教程系列以一个**数据分析助手 DataMuse** 为业务主线：学生始终围绕同一份销售数据解决“读取、分析、解释、交付报告”的问题，再逐步学习工具调用、权限控制、人机协作、流式 UI、上下文管理、中间件、服务化、定时任务和多 Agent 协作。

这里复用的是**业务目标和数据语境**，不是要求 16 章始终运行同一个 Python 进程。随着部署方式和协作方式变化，DataMuse 会出现三种应用形态。

## DataMuse 的三种应用形态

| 形态 | 章节 | 解决的问题 |
|---|---|---|
| 本地单 Agent | T01-T12，T16 收束 | 从最小对话开始，逐块加入 Tool、Permission、HITL、Context、Middleware 和 Workspace，最后组装成自包含应用 |
| Agent Service | T13-T14 | 把相同能力放到 HTTP 服务中，支持多用户、Session、SSE 和定时任务 |
| Agent Team | T15 | 当工具、上下文、并行性或责任边界确实需要拆分时，把 DataMuse 展开为多个角色 |

推荐顺序是先掌握单 Agent，再根据应用需要选择服务化或团队化。Multi-Agent 不是“更完整”的必经阶段，T16 也不会为了形式完整而把三种架构强行塞进一个示例。

## 目标受众

有 LLM API 调用经验的**中级开发者**，了解 Agent 基本概念，想系统学习 AgentScope 2.0。

## 前置要求

- Python 3.12
- AgentScope 2.0.4（`pip install agentscope==2.0.4`）
- 至少一个 LLM API Key（DashScope / OpenAI / Ollama）

本教程按 AgentScope 2.0.4 编写；使用其他版本时，API 可能存在差异。

## 教程列表

### Phase 1: 基础篇

| # | 主题 | 你将学到 |
|---|------|----------|
| [01](01_hello_agentscope/) | **Hello AgentScope** | 核心四要素、reply vs reply_stream、切换模型 |
| [02](02_message_and_event/) | **Message & Event** | 消息结构、事件生命周期、append_event 重建消息 |
| [03](03_tools/) | **Tool 系统** | 内置工具、FunctionTool、自定义 ToolBase |

### Phase 2: 进阶篇

| # | 主题 | 你将学到 |
|---|------|----------|
| [04](04_tool_groups/) | **Tool Group** | 工具分组、动态切换、reset_tools 元工具 |
| [05](05_mcp_integration/) | **MCP 集成** | MCP 协议、Stdio/HTTP 连接、与本地工具混合使用 |
| [06](06_skills/) | **Skill** | Markdown 技能定义、`Skill` 工具、按需加载 |
| [07](07_permissions/) | **Permission 系统** | 五种模式、规则配置、危险路径保护 |
| [08](08_human_in_the_loop/) | **Human-in-the-Loop** | 用户确认、外部执行、渐进式信任 |
| [09](09_streaming_ui/) | **流式 UI** | 事件分发、Token 追踪、终端 UI |
| [10](10_context_management/) | **Context 管理** | 上下文压缩、工具结果截断、Offloader |

### Phase 3: 工程篇

| # | 主题 | 你将学到 |
|---|------|----------|
| [11](11_middleware/) | **Middleware** | 执行 Hook、压缩 Hook、TracingMiddleware、计费/日志 |
| [12](12_workspace/) | **Workspace** | LocalWorkspace、Docker/E2B 隔离、Offloader、MCP/Skill 管理 |
| [13](13_agent_service/) | **Agent Service** | FastAPI 服务、多租户、Session、Credential、Web UI、**模型 fallback / 自动重试** |
| [14](14_scheduling/) | **Schedule** | Cron 定时任务、Stateful/Stateless 模式 |

### Phase 4: 高级篇

| # | 主题 | 你将学到 |
|---|------|----------|
| [15](15_multi_agent/) | **Multi-Agent** | 多 Agent 编排、observe()、串行/并行/动态路由 |
| [16](16_complete_datamuse/) | **Complete DataMuse** | 把本地单 Agent 核心模块收束为命令行与轻量 Web 应用 |

## 示例数据

所有教程共用同一份电商销售数据集 `data/sales_data.csv`（1000 行），包含：

```
order_id, date, product, category, quantity, unit_price, discount, total, region, payment_method, customer_tier
```

生成方式：

```bash
cd tutorials/data
python generate_sales_data.py
```

## 快速开始

如果希望从零搭出一个可服务化 Agent 应用，请直接使用 [AgentScope 2.0 完整入门教程](QUICKSTART.md)。

如果希望先系统理解各模块的职责、接线位置和选型边界，再查看完整组装示例，请阅读
[AgentScope 2.0 模块全景与完整应用](MODULE_GUIDE.md)。

```bash
# 准备环境
conda create -n agentscope-tutorial-py312 python=3.12 -y
conda activate agentscope-tutorial-py312
pip install agentscope==2.0.4

# 设置 API Key
export DASHSCOPE_API_KEY="your-key"

# 运行第一个教程
cd tutorials/01_hello_agentscope
python main.py
```

## 最终整合

如果你想先看完整应用的样子，可以直接运行 [16_complete_datamuse](16_complete_datamuse/)：

```bash
# 如果还没有准备环境，先执行：
conda create -n agentscope-tutorial-py312 python=3.12 -y
conda activate agentscope-tutorial-py312
pip install agentscope==2.0.4
export DASHSCOPE_API_KEY="your-key"

cd tutorials/16_complete_datamuse
python main.py
```

它会把 T01-T12 中适合本地应用的关键模块收束成一个最小可用的 DataMuse：读取销售数据、做维度拆解、在写报告前触发确认，并把 Markdown 报告保存到本地 workspace。T13-T15 则分别保留为服务化、调度和团队化的独立扩展路径。
