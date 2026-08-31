# -*- coding: utf-8 -*-
"""Tutorial 10: Context Management — Long conversations & large results.

This tutorial demonstrates:
- ContextConfig parameters (trigger_ratio, reserve_ratio, tool_result_limit)
- Automatic context compression
- Tool result truncation
- Manual compress_context() usage
"""
# pylint: disable=missing-function-docstring,unused-argument
import asyncio
import csv
import os
from pathlib import Path
from typing import Any

from agentscope.agent import Agent, ContextConfig
from agentscope.credential import DashScopeCredential
from agentscope.event import EventType
from agentscope.message import UserMsg, TextBlock
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
    Read,
    Glob,
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


class LargeResultTool(ToolBase):
    """A tool that returns a large result to demonstrate truncation."""

    name = "LargeResultTool"
    description = "Returns all sales data rows (large result for demo)."
    input_schema = {
        "type": "object",
        "properties": {
            "max_rows": {
                "type": "integer",
                "description": "Maximum rows to return.",
                "default": 100,
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
            message="Read-only, always allowed.",
        )

    async def call(self, max_rows: int = 100) -> ToolChunk:
        rows = []
        with open(SALES_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
                if len(rows) >= max_rows:
                    break

        lines = []
        for row in rows:
            lines.append(" | ".join(f"{k}={v}" for k, v in row.items()))
        text = f"Returning {len(rows)} rows:\n" + "\n".join(lines)
        return ToolChunk(content=[TextBlock(text=text)])


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
            case EventType.MODEL_CALL_END:
                print(
                    f"\n  [tokens: {event.input_tokens}in "
                    f"+ {event.output_tokens}out]",
                    end="",
                )
            case EventType.REPLY_END:
                print()


# =========================================================================
# Example 1: ContextConfig overview
# =========================================================================
async def example_context_config() -> None:
    """Explain ContextConfig parameters."""
    print("\n" + "=" * 60)
    print("Example 1: ContextConfig Parameters")
    print("=" * 60)

    configs = [
        ("Default", ContextConfig()),
        (
            "Aggressive compression",
            ContextConfig(
                trigger_ratio=0.5,
                reserve_ratio=0.05,
                tool_result_limit=1000,
            ),
        ),
        (
            "Conservative compression",
            ContextConfig(
                trigger_ratio=0.85,
                reserve_ratio=0.2,
                tool_result_limit=5000,
            ),
        ),
    ]

    for name, cfg in configs:
        print(f"\n  {name}:")
        print(f"    trigger_ratio:    {cfg.trigger_ratio}")
        print(f"    reserve_ratio:    {cfg.reserve_ratio}")
        print(f"    tool_result_limit: {cfg.tool_result_limit} tokens")


# =========================================================================
# Example 2: Tool result truncation
# =========================================================================
async def example_tool_result_truncation(model) -> None:
    """Demonstrate tool result truncation with different limits."""
    print("\n" + "=" * 60)
    print("Example 2: Tool Result Truncation")
    print("=" * 60)

    for limit in [500, 3000]:
        print(f"\n  --- tool_result_limit={limit} ---")

        agent = Agent(
            name="DataMuse",
            system_prompt=(
                "You are DataMuse. Use LargeResultTool to fetch data, "
                "then summarize the result briefly."
            ),
            model=model,
            toolkit=Toolkit(
                tools=[
                    LargeResultTool(),
                    FunctionTool(query_sales, is_read_only=True),
                ],
            ),
            context_config=ContextConfig(tool_result_limit=limit),
            state=AgentState(
                permission_context=PermissionContext(
                    mode=PermissionMode.BYPASS,
                ),
            ),
        )

        await stream_reply(
            agent,
            "Fetch 50 rows of sales data using LargeResultTool and "
            "tell me how many rows you received.",
        )


# =========================================================================
# Example 3: Multi-turn with context growth
# =========================================================================
async def example_multi_turn_context(model) -> None:
    """Show context growth across multiple turns."""
    print("\n" + "=" * 60)
    print("Example 3: Multi-Turn Context Growth")
    print("=" * 60)

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a data analysis assistant. Use tools to "
            "answer questions. Keep responses concise (1-2 sentences)."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[
                Read(),
                Glob(),
                FunctionTool(query_sales, is_read_only=True),
            ],
        ),
        context_config=ContextConfig(
            trigger_ratio=0.8,
            reserve_ratio=0.1,
            tool_result_limit=2000,
        ),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    questions = [
        "What categories exist in the sales data? Query 3 rows.",
        "How many Electronics orders are there? Query 5.",
        "Show me 3 orders from the North region.",
        "What's the most common payment method? Query 5 rows.",
    ]

    for i, q in enumerate(questions, 1):
        print(f"\n  --- Turn {i}/{len(questions)} ---")
        n_msgs = len(agent.state.context)
        print(f"  Context messages before: {n_msgs}")
        await stream_reply(agent, q)
        n_msgs_after = len(agent.state.context)
        print(f"  Context messages after: {n_msgs_after}")


# =========================================================================
# Example 4: Compression flow diagram
# =========================================================================
async def example_compression_flow() -> None:
    """Display the compression flow."""
    print("\n" + "=" * 60)
    print("Example 4: Context Compression Flow")
    print("=" * 60)

    print(
        """
  Automatic Compression (triggered in each reasoning iteration):
  ──────────────────────────────────────────────────────────────

  estimate current tokens
      │
      ├─ tokens < context_size × trigger_ratio
      │   └─ skip (no compression needed)
      │
      └─ tokens >= context_size × trigger_ratio
          │
          ├─ Split context: [old messages | recent messages]
          │   (recent = reserve_ratio of context)
          │
          ├─ Generate structured summary of old messages:
          │   • task_overview: user's core request
          │   • current_state: what's been done
          │   • important_discoveries: key findings
          │   • next_steps: what remains
          │   • context_to_preserve: important details
          │
          └─ Replace old messages with summary
              → new context = [system_prompt, summary, recent messages]

  Tool Result Truncation (applied during tool execution):
  ──────────────────────────────────────────────────────

  tool returns result
      │
      ├─ result tokens <= tool_result_limit
      │   └─ keep as-is
      │
      └─ result tokens > tool_result_limit
          └─ truncate to fit limit
              (or offload to workspace if Offloader available)

  Manual Compression:
  ──────────────────
  await agent.compress_context()                    # default config
  await agent.compress_context(context_config=custom_config)
  await agent.compress_context(instructions=hint_block)
      # hint_block tells the summarizer what must be preserved
""",
    )


# =========================================================================
# Main
# =========================================================================
async def main() -> None:
    print("Tutorial 10: Context Management")
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

    await example_context_config()
    await example_tool_result_truncation(model)
    await example_multi_turn_context(model)
    await example_compression_flow()

    print("\n" + "=" * 60)
    print("Tutorial 10 complete! Next: Tutorial 11 — Middleware")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
