# -*- coding: utf-8 -*-
"""Tutorial 11: Middleware — Pluggable behavior extensions.

This tutorial demonstrates:
- Creating custom middleware with MiddlewareBase
- Onion pattern hooks (on_reply, on_reasoning, on_acting, on_model_call)
- Compression hook (on_compress_context)
- Transformer pattern hook (on_system_prompt)
- Middleware execution order
- TracingMiddleware for OpenTelemetry integration
"""
# pylint: disable=missing-function-docstring,unused-argument
import asyncio
import csv
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Awaitable, Callable

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.event import EventType
from agentscope.message import UserMsg, TextBlock, HintBlock
from agentscope.middleware import MiddlewareBase
from agentscope.model import DashScopeChatModel
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
    PermissionMode,
)
from agentscope.state import AgentState
from agentscope.tool import (
    Toolkit,
    ToolBase,
    ToolChunk,
    FunctionTool,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SALES_CSV = DATA_DIR / "sales_data.csv"


# =========================================================================
# Tools
# =========================================================================
def query_sales(category: str = "", limit: int = 5) -> ToolChunk:
    """Query the sales dataset.

    Args:
        category: Product category to filter. Empty means no filter.
        limit: Maximum number of rows to return.
    """
    rows = []
    with open(SALES_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if category and row["category"] != category:
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
    if not rows:
        return ToolChunk(
            content=[TextBlock(text="No matching records found.")],
        )
    header = " | ".join(rows[0].keys())
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(" | ".join(row.values()))
    return ToolChunk(
        content=[
            TextBlock(text=f"Found {len(rows)} records:\n" + "\n".join(lines)),
        ],
    )


class SalesSummary(ToolBase):
    """Compute aggregate statistics on the sales dataset."""

    name = "SalesSummary"
    description = "Compute summary statistics for the sales dataset."
    input_schema = {
        "type": "object",
        "properties": {
            "group_by": {
                "type": "string",
                "description": "Column to group by. Empty for overall.",
                "default": "",
            },
        },
        "required": [],
    }
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Read-only analytics, always allowed.",
        )

    async def call(self, group_by: str = "") -> ToolChunk:
        rows = []
        with open(SALES_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)

        if not group_by:
            total = sum(float(r["total"]) for r in rows)
            avg = total / len(rows) if rows else 0
            return ToolChunk(
                content=[
                    TextBlock(
                        text=f"Overall: {len(rows)} orders, "
                        f"${total:,.2f} revenue, ${avg:,.2f} avg",
                    ),
                ],
            )

        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(row.get(group_by, "?"), []).append(row)

        lines = [f"Summary by '{group_by}':"]
        for key in sorted(groups):
            g = groups[key]
            rev = sum(float(r["total"]) for r in g)
            lines.append(f"  {key}: {len(g)} orders, ${rev:,.2f}")
        return ToolChunk(content=[TextBlock(text="\n".join(lines))])


# =========================================================================
# Custom Middlewares
# =========================================================================
class LoggingMiddleware(MiddlewareBase):
    """Logs reply start/end events."""

    async def on_reply(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        print(f"  [LOG] Reply started for '{agent.name}'")
        start = time.time()
        async for event in next_handler(**input_kwargs):
            yield event
        elapsed = time.time() - start
        print(f"  [LOG] Reply ended for '{agent.name}' ({elapsed:.1f}s)")


class TimingMiddleware(MiddlewareBase):
    """Measures model call duration."""

    async def on_model_call(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[..., Awaitable],
    ):
        start = time.time()
        result = await next_handler(**input_kwargs)
        elapsed = time.time() - start
        print(f"  [TIME] Model call: {elapsed:.2f}s")
        return result


class CostTrackerMiddleware(MiddlewareBase):
    """Tracks cumulative token usage across replies."""

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.call_count = 0

    async def on_reasoning(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        self.call_count += 1
        async for event in next_handler(**input_kwargs):
            if (
                hasattr(event, "type")
                and event.type == EventType.MODEL_CALL_END
            ):
                self.total_input_tokens += event.input_tokens
                self.total_output_tokens += event.output_tokens
            yield event

    def summary(self) -> str:
        total = self.total_input_tokens + self.total_output_tokens
        return (
            f"Reasoning calls: {self.call_count} | "
            f"Tokens: {self.total_input_tokens}in "
            f"+ {self.total_output_tokens}out "
            f"= {total} total"
        )


class DynamicPromptMiddleware(MiddlewareBase):
    """Injects dynamic information into the system prompt."""

    async def on_system_prompt(
        self,
        agent: Agent,
        current_prompt: str,
    ) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (
            current_prompt
            + f"\n\nCurrent time: {now}"
            + f"\nData source: {SALES_CSV}"
        )


class CompressionHintMiddleware(MiddlewareBase):
    """Adds a preservation hint whenever context compression is requested."""

    async def on_compress_context(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[..., Awaitable[None]],
    ) -> None:
        hint = input_kwargs.get("instructions") or HintBlock(
            hint=(
                "Preserve DataMuse's KPI definitions, report format, "
                "and any user-specific reporting preferences."
            ),
        )
        print(f"  [COMPRESS] Adding preservation hint for '{agent.name}'")
        await next_handler(**{**input_kwargs, "instructions": hint})


# =========================================================================
# Stream helper
# =========================================================================
async def stream_reply(agent: Agent, content: str) -> None:
    """Send a message and stream the reply."""
    msg = UserMsg(name="user", content=content)
    print(f"\n[User]: {content[:80]}{'...' if len(content) > 80 else ''}")
    print("[DataMuse]: ", end="", flush=True)

    async for event in agent.reply_stream(msg):
        match event.type:
            case EventType.TEXT_BLOCK_DELTA:
                print(event.delta, end="", flush=True)
            case EventType.TOOL_CALL_START:
                print(f"\n  >> Calling: {event.tool_call_name}")
            case EventType.TOOL_RESULT_END:
                print(f"  >> Result: {event.state}")
            case EventType.REPLY_END:
                print()


# =========================================================================
# Example 1: Onion pattern middlewares
# =========================================================================
async def example_onion_middlewares(model) -> None:
    """Demonstrate the onion pattern with logging and timing."""
    print("\n" + "=" * 60)
    print("Example 1: Onion Pattern (Logging + Timing)")
    print("=" * 60)

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse. Use tools to answer questions. "
            "Keep responses concise."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[
                FunctionTool(query_sales, is_read_only=True),
                SalesSummary(),
            ],
        ),
        middlewares=[
            LoggingMiddleware(),
            TimingMiddleware(),
        ],
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    await stream_reply(
        agent,
        "Show me a summary of sales grouped by category.",
    )


# =========================================================================
# Example 2: Cost tracking middleware
# =========================================================================
async def example_cost_tracking(model) -> None:
    """Track token costs across multiple replies."""
    print("\n" + "=" * 60)
    print("Example 2: Cost Tracking Middleware")
    print("=" * 60)

    cost_tracker = CostTrackerMiddleware()

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse. Use tools to answer questions. "
            "Keep responses concise (1-2 sentences)."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[
                FunctionTool(query_sales, is_read_only=True),
                SalesSummary(),
            ],
        ),
        middlewares=[cost_tracker],
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    await stream_reply(agent, "Query 3 Electronics orders.")
    print(f"  [COST] After turn 1: {cost_tracker.summary()}")

    await stream_reply(agent, "Now show summary grouped by region.")
    print(f"  [COST] After turn 2: {cost_tracker.summary()}")


# =========================================================================
# Example 3: Dynamic prompt middleware
# =========================================================================
async def example_dynamic_prompt(model) -> None:
    """Inject dynamic information into the system prompt, then act on it."""
    print("\n" + "=" * 60)
    print("Example 3: Dynamic Prompt Middleware (on_system_prompt)")
    print("=" * 60)

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a sales-data analyst. The current snapshot "
            "time and active data source are appended to this prompt by the "
            "framework — quote them verbatim in your reply, then use the "
            "available tools to compute the headline numbers from that data "
            "source."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[
                FunctionTool(query_sales, is_read_only=True),
                SalesSummary(),
            ],
        ),
        middlewares=[DynamicPromptMiddleware()],
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    await stream_reply(
        agent,
        "Use the snapshot time injected into your system prompt as the "
        "report timestamp, then call SalesSummary grouped by category and "
        "tell me the top category by revenue.",
    )


# =========================================================================
# Example 4: Compression hook
# =========================================================================
async def example_compression_hook(model) -> None:
    """Show how middleware can intercept manual context compression."""
    print("\n" + "=" * 60)
    print("Example 4: Compression Hook (on_compress_context)")
    print("=" * 60)

    agent = Agent(
        name="DataMuse",
        system_prompt="You are DataMuse, a sales-data analyst.",
        model=model,
        toolkit=Toolkit(tools=[]),
        middlewares=[CompressionHintMiddleware()],
    )
    await agent.observe(
        UserMsg(
            name="user",
            content=(
                "For future reports, preserve the KPI definitions and "
                "keep summaries in bullet form."
            ),
        ),
    )
    await agent.compress_context()
    print("  [COMPRESS] compress_context() completed")


# =========================================================================
# Example 5: Middleware architecture
# =========================================================================
async def example_architecture() -> None:
    """Display the middleware architecture."""
    print("\n" + "=" * 60)
    print("Example 5: Middleware Architecture")
    print("=" * 60)

    print(
        """
  Onion Model:
  ────────────
  on_reply / on_reasoning / on_acting / on_model_call
  on_compress_context

  middlewares = [A, B, C]

  Request:   A.before → B.before → C.before → core logic
  Response:  A.after  ← B.after  ← C.after  ← core logic

  ┌─────────────────────────────────────────────┐
  │ A: on_reply                                 │
  │   ┌─────────────────────────────────────┐   │
  │   │ B: on_reasoning                     │   │
  │   │   ┌─────────────────────────────┐   │   │
  │   │   │ C: on_model_call            │   │   │
  │   │   │   ┌─────────────────────┐   │   │   │
  │   │   │   │    Core Logic       │   │   │   │
  │   │   │   └─────────────────────┘   │   │   │
  │   │   └─────────────────────────────┘   │   │
  │   └─────────────────────────────────────┘   │
  └─────────────────────────────────────────────┘

  Transformer Model (on_system_prompt):
  ─────────────────────────────────────

  prompt → A.transform → B.transform → C.transform → final prompt

  Each middleware receives the output of the previous one.
  Unlike onion, there's no "after" phase.

  Implementation pattern:
  ──────────────────────

  # Onion hook (async generator):
  async def on_reasoning(self, agent, input_kwargs, next_handler):
      # Before logic
      async for event in next_handler(**input_kwargs):
          yield event    # Forward events
      # After logic

  # Transformer hook (returns string):
  async def on_system_prompt(self, agent, current_prompt):
      return current_prompt + "\\nExtra info"

  # Compression hook (returns None):
  async def on_compress_context(self, agent, input_kwargs, next_handler):
      await next_handler(**input_kwargs)

  Optional tool discovery:
  ───────────────────────
  async def list_tools(self):
      return [SomeTool()]

  In library mode, add those tools to Toolkit yourself.
  In Agent Service, the toolkit assembly step collects middleware tools.
""",
    )


# =========================================================================
# Main
# =========================================================================
async def main() -> None:
    print("Tutorial 11: Middleware")
    print("=" * 60)

    if not SALES_CSV.exists():
        print(f"ERROR: {SALES_CSV} not found.")
        print("Run: cd tutorials/data && python generate_sales_data.py")
        return

    model = DashScopeChatModel(
        credential=DashScopeCredential(
            api_key=os.environ["DASHSCOPE_API_KEY"],
        ),
        model="qwen-plus",
    )

    await example_onion_middlewares(model)
    await example_cost_tracking(model)
    await example_dynamic_prompt(model)
    await example_compression_hook(model)
    await example_architecture()

    print("\n" + "=" * 60)
    print("Tutorial 11 complete! Next: Tutorial 12 — Workspace")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
