# -*- coding: utf-8 -*-
"""Tutorial 03: Tool System — Give your Agent the ability to act.

This tutorial demonstrates:
- Using built-in tools (Bash, Read, Glob) for file operations
- Wrapping Python functions with FunctionTool
- Creating custom ToolBase subclasses
- The full tool execution lifecycle
"""
# pylint: disable=missing-function-docstring,unused-argument
import asyncio
import csv
import os
from pathlib import Path
from typing import Any

from agentscope.agent import Agent
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
    Bash,
    Read,
    Glob,
    Grep,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SALES_CSV = DATA_DIR / "sales_data.csv"


# =========================================================================
# Custom tools
# =========================================================================


def query_sales(
    category: str = "",
    region: str = "",
    min_total: float = 0.0,
    limit: int = 10,
) -> str:
    """Query and filter the sales dataset.

    Args:
        category: Product category to filter (e.g. "Electronics"). Empty
            string means no filter.
        region: Region to filter (e.g. "North"). Empty string means no filter.
        min_total: Minimum order total to include in results.
        limit: Maximum number of rows to return.
    """
    rows = []
    with open(SALES_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if category and row["category"] != category:
                continue
            if region and row["region"] != region:
                continue
            if float(row["total"]) < min_total:
                continue
            rows.append(row)
            if len(rows) >= limit:
                break

    if not rows:
        return "No matching records found."

    header = " | ".join(rows[0].keys())
    separator = "-" * len(header)
    lines = [header, separator]
    for row in rows:
        lines.append(" | ".join(row.values()))

    return f"Found {len(rows)} records:\n" + "\n".join(lines)


class SalesSummary(ToolBase):
    """A custom tool that computes aggregate statistics on sales data."""

    name = "SalesSummary"
    description = (
        "Compute summary statistics (count, total revenue, average order "
        "value) for the sales dataset, optionally grouped by a column."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "group_by": {
                "type": "string",
                "description": "Column to group by: 'category', 'region', "
                "'payment_method', or 'customer_tier'. "
                "Leave empty for overall summary.",
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
            message="Read-only analytics tool, always allowed.",
        )

    async def call(self, group_by: str = "") -> ToolChunk:
        rows = []
        with open(SALES_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

        if not group_by:
            total_revenue = sum(float(r["total"]) for r in rows)
            avg_order = total_revenue / len(rows) if rows else 0
            text = (
                f"Overall Summary:\n"
                f"  Total orders: {len(rows)}\n"
                f"  Total revenue: ${total_revenue:,.2f}\n"
                f"  Average order value: ${avg_order:,.2f}"
            )
            return ToolChunk(content=[TextBlock(text=text)])

        groups: dict[str, list] = {}
        for row in rows:
            key = row.get(group_by, "Unknown")
            groups.setdefault(key, []).append(row)

        lines = [f"Summary grouped by '{group_by}':\n"]
        lines.append(f"{'Group':<20} {'Count':>6} {'Revenue':>14} {'Avg':>10}")
        lines.append("-" * 55)

        for key in sorted(groups.keys()):
            group_rows = groups[key]
            count = len(group_rows)
            revenue = sum(float(r["total"]) for r in group_rows)
            avg = revenue / count if count else 0
            lines.append(
                f"{key:<20} {count:>6} ${revenue:>12,.2f} ${avg:>8,.2f}",
            )

        return ToolChunk(content=[TextBlock(text="\n".join(lines))])


# =========================================================================
# Example 1: Built-in tools
# =========================================================================
async def example_builtin_tools(agent: Agent) -> None:
    """Use built-in tools to explore the sales data file."""
    print("\n" + "=" * 60)
    print("Example 1: Built-in Tools (Read, Glob, Bash)")
    print("=" * 60)

    msg = UserMsg(
        name="user",
        content=f"Read the first 10 lines of {SALES_CSV} and tell me "
        f"what columns are available and what the data looks like.",
    )

    print("\n[User]: " + msg.get_text_content()[:80] + "...")
    print("\n[DataMuse]: ", end="", flush=True)

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
# Example 2: FunctionTool
# =========================================================================
async def example_function_tool(agent: Agent) -> None:
    """Use a FunctionTool-wrapped query function."""
    print("\n" + "=" * 60)
    print("Example 2: FunctionTool (query_sales)")
    print("=" * 60)

    msg = UserMsg(
        name="user",
        content="Use the query_sales tool to find Electronics orders "
        "from the North region with total > 500. Show me the results.",
    )

    print("\n[User]: " + msg.get_text_content())
    print("\n[DataMuse]: ", end="", flush=True)

    async for event in agent.reply_stream(msg):
        match event.type:
            case EventType.TEXT_BLOCK_DELTA:
                print(event.delta, end="", flush=True)
            case EventType.TOOL_CALL_START:
                print(f"\n  >> Calling: {event.tool_call_name}")
            case EventType.TOOL_RESULT_TEXT_DELTA:
                pass  # suppress raw tool output for clarity
            case EventType.TOOL_RESULT_END:
                print(f"  >> Result: {event.state}")
            case EventType.REPLY_END:
                print()


# =========================================================================
# Example 3: Custom ToolBase
# =========================================================================
async def example_custom_tool(agent: Agent) -> None:
    """Use the custom SalesSummary tool."""
    print("\n" + "=" * 60)
    print("Example 3: Custom ToolBase (SalesSummary)")
    print("=" * 60)

    msg = UserMsg(
        name="user",
        content="Use the SalesSummary tool to show me a summary grouped by "
        "category, then by region. Compare the results and tell me "
        "which category and region have the highest revenue.",
    )

    print("\n[User]: " + msg.get_text_content()[:80] + "...")
    print("\n[DataMuse]: ", end="", flush=True)

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
# Main
# =========================================================================
async def main() -> None:
    print("Tutorial 03: Tool System")
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

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a data analysis assistant equipped with tools "
            "to read files, run commands, and analyze data. Use the available "
            "tools to answer the user's questions. Always show your findings "
            "clearly."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[
                # Built-in tools
                Bash(),
                Read(),
                Glob(),
                Grep(),
                # FunctionTool adapter
                FunctionTool(query_sales, is_read_only=True),
                # Custom ToolBase
                SalesSummary(),
            ],
        ),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    print(f"Agent: {agent.name}")
    print(f"Data:  {SALES_CSV}")

    await example_builtin_tools(agent)
    await example_function_tool(agent)
    await example_custom_tool(agent)

    print("\n" + "=" * 60)
    print("Tutorial 03 complete! Next: Tutorial 04 — Tool Groups")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
