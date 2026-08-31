# AgentScope 2.0 完整入门：从零搭建可服务化 Agent 应用

本教程以 DataMuse 销售分析助手为例，从空目录开始，逐步搭建一个能调用真实工具、输出流式事件，并可以通过 HTTP/SSE 对外提供服务的 Agent 应用。

最终应用包含两种运行方式：

- 本地模式：Toolkit 同时装配 Python Tool、filesystem MCP 和报告 Skill，通过事件流展示运行过程，并在写文件前请求审批。
- 服务模式：同一组能力由 Agent Service 托管，通过 REST 创建 Agent 和 Session，通过 SSE 返回事件和审批请求。

最终项目结构如下：

```text
tutorials/datamuse_app/
├── skills/
│   └── report_writer/
│       └── SKILL.md  # 按需加载的报告编写指南
├── tools.py          # SalesSummary + 需要审批的 ReportWriter
├── local_app.py      # Python Tool + MCP + Skill 的本地 Agent
├── service.py        # Agent Service 入口
├── client.py         # REST + SSE + 审批客户端
└── reports/          # 审批通过后生成的报告
```

## AgentScope 2.0 的核心特色

AgentScope 2.0 不只是封装一次模型请求，而是提供构建完整 Agent 应用所需的运行时能力：

- **Agent 原生异步**：`reply()` 和 `reply_stream()` 统一支持多轮推理、工具调用和流式输出。
- **结构化消息与事件**：文本、思考、工具调用、工具结果、用户确认等过程都有明确的数据结构，便于连接终端、Web UI 和日志系统。
- **统一工具体系**：Python Tool、内置文件工具、MCP 和 Skill 可以由 Toolkit 统一注册和发现。
- **权限与 Human-in-the-Loop**：工具调用可以返回 ALLOW、DENY 或 ASK，把高风险动作交给用户确认。
- **Context 与 Workspace**：上下文压缩、工具结果截断、文件空间和沙箱能力都有明确边界。
- **Middleware 扩展**：Tracing、计费、日志、长期记忆和 RAG 可以作为横切能力接入，而不需要改写 Agent 主流程。
- **内置 Agent Service**：`create_app()` 提供 Credential、Agent、Session、Chat、SSE 和 Schedule 等服务接口，让本地 Agent 可以自然过渡到多用户服务。

本教程先建立本地 Agent 的业务闭环，再把同一组工具注入 Agent Service。这样可以同时看清 AgentScope 的库模式和服务模式。

开始前准备环境和目录：

```bash
conda activate agentscope-tutorial-py312
pip install -e ".[service]" fakeredis httpx
export DASHSCOPE_API_KEY="your-key"

mkdir -p tutorials/datamuse_app/skills/report_writer
cd tutorials/datamuse_app
npx --version
```

仓库已经包含 `tutorials/data/sales_data.csv`，两种运行方式都会读取这份数据。

filesystem MCP 通过 `npx` 启动，因此需要提前安装 Node.js。第一次运行时，`npx` 会下载 `@modelcontextprotocol/server-filesystem`。

---

## 搭建能调用真实工具的本地 Agent

先完成最小业务闭环：用户提出销售问题，DataMuse 判断应该调用哪个工具，工具读取 CSV 并返回真实数据，Agent 再组织最终回答。

### 1. AgentScope 应用的基本结构

```text
Credential → ChatModel → Agent
                         ├── Msg：用户输入和对话上下文
                         ├── Toolkit：Agent 当前可调用的工具
                         ├── Permission：工具调用边界
                         └── Event：文本、模型调用、工具调用等运行过程
```

各部分的职责：

| 组件 | 做什么 | 什么时候需要 |
|---|---|---|
| Credential | 保存模型服务认证信息 | 调用任何远程模型时 |
| ChatModel | 适配具体模型提供商 | 选择 DashScope、OpenAI、Ollama 等模型时 |
| Agent | 维护提示词、上下文和 reasoning-acting 循环 | 应用需要多轮推理或工具调用时 |
| Msg | 表示用户、助手和系统消息 | 向 Agent 输入结构化内容时 |
| Toolkit | 注册 Python Tool、MCP 和 Skill | Agent 需要访问真实数据、外部服务或操作指南时 |
| Permission | 对工具调用做 ALLOW、DENY、ASK 判定 | 工具会读取、修改或访问外部系统时 |
| Event | 暴露 Agent 的运行过程 | 构建终端、Web UI、日志或 HITL 时 |

### 2. 定义 Python Tool

新建 `tools.py`：

```python
import csv
import re
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
)
from agentscope.tool import ToolBase, ToolChunk


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SALES_CSV = DATA_DIR / "sales_data.csv"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"


class SalesSummary(ToolBase):
    """Summarize the shared sales dataset by a business dimension."""

    name = "SalesSummary"
    description = (
        "Read the sales dataset and calculate order count, revenue, and "
        "average order value grouped by category or region."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "group_by": {
                "type": "string",
                "enum": ["category", "region"],
                "description": "Business dimension used for grouping.",
            },
        },
        "required": ["group_by"],
    }
    is_read_only = True
    is_concurrency_safe = True

    async def check_permissions(
        self,
        _tool_input: dict[str, Any],
        _context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="SalesSummary only reads the fixed demo dataset.",
        )

    async def call(self, group_by: str) -> ToolChunk:
        with SALES_CSV.open("r", encoding="utf-8") as csv_file:
            rows = list(csv.DictReader(csv_file))

        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            groups.setdefault(row[group_by], []).append(row)

        lines = [
            f"Sales summary by {group_by}",
            "group | orders | revenue | avg_order",
            "--- | ---: | ---: | ---:",
        ]
        for name, group_rows in sorted(groups.items()):
            revenue = sum(float(row["total"]) for row in group_rows)
            average = revenue / len(group_rows)
            lines.append(
                f"{name} | {len(group_rows)} | ${revenue:,.2f} | "
                f"${average:,.2f}",
            )

        return ToolChunk(content=[TextBlock(text="\n".join(lines))])


class ReportWriter(ToolBase):
    """Write an approved Markdown report to the application directory."""

    name = "ReportWriter"
    description = (
        "Write a completed sales analysis report to a Markdown file. "
        "Call this only after the analysis is complete."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Report title.",
            },
            "markdown": {
                "type": "string",
                "description": "Complete Markdown report body.",
            },
            "filename": {
                "type": "string",
                "description": "Output filename.",
                "default": "sales_report.md",
            },
        },
        "required": ["title", "markdown"],
    }
    is_read_only = False
    is_concurrency_safe = False

    async def check_permissions(
        self,
        _tool_input: dict[str, Any],
        _context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            message="ReportWriter creates a file and requires approval.",
        )

    async def call(
        self,
        title: str,
        markdown: str,
        filename: str = "sales_report.md",
    ) -> ToolChunk:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename).strip("._")
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        output_path = REPORTS_DIR / safe_name
        output_path.write_text(
            f"# {title}\n\n{markdown.strip()}\n",
            encoding="utf-8",
        )
        return ToolChunk(
            content=[TextBlock(text=f"Report written to {output_path}")],
        )


def build_tools() -> list[ToolBase]:
    """Build fresh tools for a local Agent."""
    return [SalesSummary(), ReportWriter()]


async def build_service_tools(
    _user_id: str,
    _agent_id: str,
    _session_id: str,
) -> list[ToolBase]:
    """Build fresh tools whenever Agent Service assembles an Agent."""
    return build_tools()
```

这里选择自定义 `ToolBase`，是因为同一工具随后还要注入 Agent Service，并且需要明确声明权限行为：

- `input_schema` 告诉模型应该怎样调用工具。
- `is_read_only=True` 描述工具没有写入副作用。
- `SalesSummary.check_permissions()` 返回 ALLOW，因为它只读取固定数据。
- `ReportWriter.check_permissions()` 返回 ASK，因为它会创建文件。
- `call()` 执行真实计算并返回 `ToolChunk`。
- `build_tools()` 和 `build_service_tools()` 分别对应本地组装和服务端组装。

### 3. 添加 Skill

Skill 不是可执行函数，而是一份按需加载的操作指南。Toolkit 只把 Skill 的名称和描述放进系统提示；需要执行对应任务时，Agent 再调用内置的 `Skill` 工具读取完整内容。

新建 `skills/report_writer/SKILL.md`：

```markdown
---
name: report_writer
description: Create a concise Markdown sales analysis report from verified tool results.
---

# Report Writer

1. Only use figures returned by SalesSummary.
2. Start with an executive summary, then list key findings and actions.
3. Keep the report concise and include the grouping dimension.
4. Call ReportWriter only after the complete Markdown body is ready.
5. Use `sales_report.md` as the default filename.
```

Skill 解决的是“应该按什么步骤组合工具”，Python Tool 解决的是“具体执行什么动作”。二者不能互相替代。

### 4. 接入 MCP 并创建本地 Agent

Toolkit 可以同时接收三类能力来源：

| 来源 | 本例 | 作用 |
|---|---|---|
| `tools` | `SalesSummary`、`ReportWriter` | 本地 Python 业务能力 |
| `mcps` | filesystem MCP | 通过标准协议列目录、读取文件 |
| `skills_or_loaders` | `report_writer` | 按需加载报告编写指南 |

MCP 工具会使用 `mcp__{server_name}__{tool_name}` 命名空间，避免多个服务出现同名工具。Skill 存在时，Toolkit 会额外暴露名为 `Skill` 的只读工具。

新建 `local_app.py`：

```python
import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.event import (
    AgentEvent,
    ConfirmResult,
    EventType,
    UserConfirmResultEvent,
)
from agentscope.mcp import MCPClient, StdioMCPConfig
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.skill import LocalSkillLoader
from agentscope.state import AgentState
from agentscope.tool import Toolkit

from tools import DATA_DIR, build_tools


SKILLS_DIR = Path(__file__).resolve().parent / "skills"


async def stream_with_approval(agent: Agent, message: UserMsg) -> None:
    """Render events and resume the Agent after user confirmation."""

    async def process(stream: AsyncIterator[AgentEvent]) -> None:
        async for event in stream:
            if event.type == EventType.TOOL_CALL_START:
                print(f"\n[tool] {event.tool_call_name}")

            elif event.type == EventType.TOOL_RESULT_END:
                print(f"[tool result] {event.state}")

            elif event.type == EventType.TEXT_BLOCK_DELTA:
                print(event.delta, end="", flush=True)

            elif event.type == EventType.REQUIRE_USER_CONFIRM:
                results = []
                for tool_call in event.tool_calls:
                    print(f"\n[approval required] {tool_call.name}")
                    print(f"input: {tool_call.input}")
                    answer = await asyncio.to_thread(
                        input,
                        "Approve this tool call? [y/N] ",
                    )
                    results.append(
                        ConfirmResult(
                            confirmed=answer.strip().lower() == "y",
                            tool_call=tool_call,
                        ),
                    )

                await process(
                    agent.reply_stream(
                        UserConfirmResultEvent(
                            reply_id=event.reply_id,
                            confirm_results=results,
                        ),
                    ),
                )

            elif event.type == EventType.REPLY_END:
                print()

    await process(agent.reply_stream(message))


async def main() -> None:
    model = DashScopeChatModel(
        credential=DashScopeCredential(
            api_key=os.environ["DASHSCOPE_API_KEY"],
        ),
        model="qwen-plus",
    )

    filesystem_mcp = MCPClient(
        name="filesystem",
        is_stateful=True,
        mcp_config=StdioMCPConfig(
            command="npx",
            args=[
                "-y",
                "@modelcontextprotocol/server-filesystem",
                str(DATA_DIR),
            ],
        ),
        enable_tools=["list_directory", "read_file"],
    )
    await filesystem_mcp.connect()

    try:
        agent = Agent(
            name="DataMuse",
            system_prompt=(
                "You are DataMuse, a concise sales-data analyst. "
                "Use filesystem MCP tools to inspect available data files. "
                "Use SalesSummary for every sales figure. Before writing "
                "a report, call Skill with skill='report_writer', follow "
                "its instructions, then call ReportWriter."
            ),
            model=model,
            toolkit=Toolkit(
                tools=build_tools(),
                mcps=[filesystem_mcp],
                skills_or_loaders=[
                    LocalSkillLoader(
                        directory=str(SKILLS_DIR),
                        scan_subdir=True,
                    ),
                ],
            ),
            state=AgentState(
                permission_context=PermissionContext(
                    mode=PermissionMode.DEFAULT,
                ),
            ),
        )

        await stream_with_approval(
            agent,
            UserMsg(
                name="user",
                content=(
                    "Use filesystem MCP to list the data directory, "
                    "summarize revenue by region, then use the "
                    "report_writer skill to write a Markdown report."
                ),
            ),
        )
    finally:
        await filesystem_mcp.close()


if __name__ == "__main__":
    asyncio.run(main())
```

运行：

```bash
conda activate agentscope-tutorial-py312
cd tutorials/datamuse_app
python local_app.py
```

`reply_stream()` 返回的是 `AgentEvent` 异步流。当前终端处理五类关键事件：

- `TOOL_CALL_START`：显示 Agent 选择了哪个工具。
- `TOOL_RESULT_END`：显示工具是否执行成功。
- `TEXT_BLOCK_DELTA`：实时打印模型生成的文本。
- `REQUIRE_USER_CONFIRM`：展示待执行工具并询问是否批准。
- `REPLY_END`：标记一次回复结束。

如果只关心最终结果，可以改用 `await agent.reply(message)`；如果要构建 UI、展示工具进度或处理用户确认，就保留 `reply_stream()`。

### 5. 权限与审批流程

权限配置通过 `state=AgentState(permission_context=...)` 装入 Agent。本例使用 `PermissionMode.DEFAULT`：只读工具可以由工具自身明确 ALLOW，写文件工具返回 ASK 并暂停执行。

五种模式的核心差异：

| 模式 | 行为 | 适用情况 |
|---|---|---|
| `DEFAULT` | 未明确允许的操作进入 ASK | 有交互界面的普通应用 |
| `ACCEPT_EDITS` | 工作目录内编辑和只读操作可自动允许 | 本地开发和代码修改 |
| `EXPLORE` | 只读 ALLOW，修改 DENY | 浏览数据或代码 |
| `BYPASS` | 跳过工具 ASK，默认 ALLOW | 完全可信的隔离环境 |
| `DONT_ASK` | 把所有 ASK 转成 DENY | 定时任务和无人值守运行 |

`BYPASS` 会跳过工具返回的安全 ASK，不能把它当作带保护的默认模式。

本例的审批链路：

```text
ReportWriter.check_permissions() → ASK
    ↓
REQUIRE_USER_CONFIRM             Agent 暂停
    ↓
终端输入 y / n
    ↓
UserConfirmResultEvent
    ↓
agent.reply_stream(confirm_event) 恢复同一次回复
```

`ConfirmResult` 不带 `rules` 时只批准当前调用；如果把事件中的 `suggested_rules` 一并返回，可以把本次决定沉淀为后续调用的权限规则。

完成本地模式后，DataMuse 已经具备完整的 Agent 运行闭环：模型负责推理，Toolkit 提供真实能力，Permission 控制调用边界，Event 暴露运行过程。

---

## 把同一个 Agent 变成 HTTP 服务

服务化过程不重写业务工具，只替换应用的组装和调用方式：工具由服务宿主注入，模型在创建 Session 时绑定，客户端通过 REST 触发运行并通过 SSE 接收事件。

### 1. 从本地对象到 Agent Service

```text
HTTP Client
   ├── POST /credential/             注册模型凭据
   ├── POST /agent/                  创建 Agent 模板
   ├── POST /sessions/               创建 Session 并绑定模型
   ├── GET  /sessions/{id}/stream    订阅 SSE 事件
   └── POST /chat/                   触发一次 Agent 运行
                         ↓
Agent Service
   ├── Storage：保存 Credential、Agent、Session 和消息
   ├── MessageBus：传递实时事件
   ├── WorkspaceManager：为 Session 注入 MCP、Skill 和工作目录
   └── extra_agent_tools：注入 SalesSummary、ReportWriter
```

Agent 和 Session 在服务模式下分工不同：

| 对象 | 保存什么 |
|---|---|
| Agent 模板 | `name`、`system_prompt`、Context/ReAct 配置 |
| Session | `agent_id`、模型配置、对话历史、运行状态 |
| 服务宿主 | Python Tool、MCP、Skill、Middleware、Storage、MessageBus、Workspace |

Python 工具不能放进 `POST /agent/` 的 JSON。`extra_agent_tools` 是工具进入服务端 Agent 的组装点。

### 2. 创建 Agent Service

新建 `service.py`：

```python
from pathlib import Path
from typing import Any

import fakeredis.aioredis
import uvicorn

from agentscope.app import create_app
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.storage import RedisStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.mcp import MCPClient, StdioMCPConfig

from tools import DATA_DIR, build_service_tools


WORKDIR = Path(__file__).resolve().parent / "workspaces"
SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def make_demo_storage() -> Any:
    """Use RedisStorage's data model with an in-process fakeredis client."""
    storage = RedisStorage.__new__(RedisStorage)
    storage._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    storage._external_pool = None
    storage._owned_pool = None
    storage.key_ttl = None
    storage.key_config = RedisStorage.KeyConfig()
    return storage


filesystem_mcp = MCPClient(
    name="filesystem",
    is_stateful=True,
    mcp_config=StdioMCPConfig(
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            str(DATA_DIR),
        ],
    ),
    enable_tools=["list_directory", "read_file"],
)


app = create_app(
    storage=make_demo_storage(),
    message_bus=InMemoryMessageBus(),
    workspace_manager=LocalWorkspaceManager(
        basedir=str(WORKDIR),
        default_mcps=[filesystem_mcp],
        skill_paths=[str(SKILLS_DIR / "report_writer")],
    ),
    extra_agent_tools=build_service_tools,
    title="DataMuse Service",
    version="1.0.0",
)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

先使用 `fakeredis`，可以在不启动外部 Redis 的情况下走通完整 HTTP 流程。`LocalWorkspaceManager` 会初始化 filesystem MCP，并把 `report_writer` Skill 放进新建的 Workspace。需要持久化或多进程部署时，把 `make_demo_storage()` 替换成真实 `RedisStorage(...)`，并把 `InMemoryMessageBus` 换成跨进程 MessageBus。

启动服务：

```bash
conda activate agentscope-tutorial-py312
cd tutorials/datamuse_app
python service.py
```

OpenAPI 文档位于 `http://localhost:8000/docs`。

### 3. 创建 REST + SSE 客户端

新建 `client.py`：

```python
import asyncio
import json
import os

import httpx


BASE_URL = "http://localhost:8000"
HEADERS = {
    "X-User-Id": "demo-user",
    "Content-Type": "application/json",
}


async def submit_approval(
    client: httpx.AsyncClient,
    agent_id: str,
    session_id: str,
    event: dict,
) -> None:
    """Ask for approval and resume the parked service-side reply."""
    results = []
    for tool_call in event["tool_calls"]:
        print(f"\n[approval required] {tool_call['name']}")
        print(f"input: {tool_call['input']}")
        answer = await asyncio.to_thread(
            input,
            "Approve this tool call? [y/N] ",
        )
        results.append(
            {
                "confirmed": answer.strip().lower() == "y",
                "tool_call": tool_call,
                "rules": None,
            },
        )

    response = await client.post(
        "/chat/",
        headers=HEADERS,
        json={
            "agent_id": agent_id,
            "session_id": session_id,
            "input": {
                "type": "USER_CONFIRM_RESULT",
                "reply_id": event["reply_id"],
                "confirm_results": results,
            },
        },
    )
    response.raise_for_status()


async def main() -> None:
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=30.0,
    ) as client:
        credential_response = await client.post(
            "/credential/",
            headers=HEADERS,
            json={
                "data": {
                    "type": "dashscope_credential",
                    "api_key": os.environ["DASHSCOPE_API_KEY"],
                },
            },
        )
        credential_response.raise_for_status()
        credential_id = credential_response.json()["credential_id"]

        agent_response = await client.post(
            "/agent/",
            headers=HEADERS,
            json={
                "name": "DataMuse",
                "system_prompt": (
                    "You are DataMuse, a concise sales-data analyst. "
                    "Use filesystem MCP tools to inspect available data "
                    "files. Use SalesSummary for every sales figure. "
                    "Before writing a report, call Skill with "
                    "skill='report_writer', follow its instructions, "
                    "then call ReportWriter."
                ),
            },
        )
        agent_response.raise_for_status()
        agent_id = agent_response.json()["agent_id"]

        session_response = await client.post(
            "/sessions/",
            headers=HEADERS,
            json={
                "agent_id": agent_id,
                "name": "DataMuse demo session",
                "chat_model_config": {
                    "type": "dashscope_chat",
                    "credential_id": credential_id,
                    "model": "qwen-plus",
                    "parameters": {},
                },
            },
        )
        session_response.raise_for_status()
        session_id = session_response.json()["session_id"]

        chat_body = {
            "agent_id": agent_id,
            "session_id": session_id,
            "input": {
                "name": "user",
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Use filesystem MCP to list the data directory, "
                            "summarize revenue by category, then use the "
                            "report_writer skill to write a Markdown report."
                        ),
                    },
                ],
            },
        }

        async with client.stream(
            "GET",
            f"/sessions/{session_id}/stream",
            params={"agent_id": agent_id},
            headers=HEADERS,
            timeout=httpx.Timeout(60.0, read=None),
        ) as stream_response:
            stream_response.raise_for_status()

            chat_response = await client.post(
                "/chat/",
                headers=HEADERS,
                json=chat_body,
            )
            chat_response.raise_for_status()

            async for line in stream_response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if not payload or payload == "[DONE]":
                    continue

                event = json.loads(payload)
                event_type = event.get("type")
                if event_type == "TOOL_CALL_START":
                    print(f"\n[tool] {event.get('tool_call_name')}")
                elif event_type == "TOOL_RESULT_END":
                    print(f"[tool result] {event.get('state')}")
                elif event_type == "TEXT_BLOCK_DELTA":
                    print(event.get("delta", ""), end="", flush=True)
                elif event_type == "REQUIRE_USER_CONFIRM":
                    await submit_approval(
                        client,
                        agent_id,
                        session_id,
                        event,
                    )
                elif event_type == "REPLY_END":
                    print()
                    break


if __name__ == "__main__":
    asyncio.run(main())
```

保持 `service.py` 运行，在另一个终端执行：

```bash
conda activate agentscope-tutorial-py312
cd tutorials/datamuse_app
python client.py
```

客户端遵循固定顺序：先创建 Credential、Agent 和 Session，再建立 SSE 连接，最后用 `/chat/` 触发运行。`POST /chat/` 只返回任务已经启动，真正的 AgentEvent 来自 `/sessions/{id}/stream`。

服务端审批沿用本地模式的同一协议：SSE 推送 `REQUIRE_USER_CONFIRM`，客户端展示工具名称和输入，随后把 `USER_CONFIRM_RESULT` 作为新的 `/chat/` 输入提交。回复恢复后产生的工具结果和文本仍然沿原 SSE 连接返回。

### 4. 从本地演示过渡到实际服务

当前代码已经具备服务化应用的主要边界：

- 使用 `X-User-Id` 隔离不同用户的资源。
- 使用 Agent 模板复用系统提示和运行配置。
- 使用 Session 隔离模型、历史消息和运行状态。
- 使用 `extra_agent_tools` 在服务宿主侧注入 Python Tool。
- 使用 WorkspaceManager 为 Session 注入 MCP、Skill 和独立工作目录。
- 使用 REST 触发任务，使用 SSE 推送运行事件。
- 使用 `REQUIRE_USER_CONFIRM` / `USER_CONFIRM_RESULT` 完成跨 HTTP 的权限审批。

进一步部署时，保持业务 Tool 和 Agent 模板不变，替换基础设施即可：

| 当前实现 | 部署时替换为 |
|---|---|
| fakeredis | 独立 Redis / 托管 Redis |
| InMemoryMessageBus | 支持多进程的 MessageBus |
| LocalWorkspaceManager | Docker、E2B 或 K8s WorkspaceManager |
| 单一模型配置 | 主模型 + `fallback_chat_model_config` |
| `X-User-Id` 直接传入 | 网关或认证中间件解析出的用户身份 |

到这里，DataMuse 已经从一个本地脚本演进为完整的可服务化 Agent 应用：Python Tool 提供业务动作，MCP 连接外部能力，Skill 提供按需操作指南，Permission/HITL 保护写入操作；同一套能力既能在本地 Agent 中运行，也能由 Agent Service 按 Session 组装，并通过标准 HTTP/SSE 接入终端、Web 或其他业务系统。

这个项目可以继续扩展图表生成、报告写入、用户确认、模型 fallback、定时任务和多 Agent 协作，但这些能力都建立在当前的 Agent、Tool、Event、Workspace 和 Session 边界之上，不需要推翻现有结构。
