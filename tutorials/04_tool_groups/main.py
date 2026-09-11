# -*- coding: utf-8 -*-
"""Tutorial 04: Tool Groups — Dynamic tool management.

This tutorial demonstrates:
- Organizing tools into functional ToolGroups
- The "basic" reserved group that stays always active
- The reset_tools meta tool for agent-driven group switching
- How group activation reduces context usage
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
    ToolGroup,
    FunctionTool,
    Bash,
    Read,
    Glob,
    Grep,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SALES_CSV = DATA_DIR / "sales_data.csv"


# =========================================================================
# Tools for each group
# =========================================================================


def query_sales(
    category: str = "",
    region: str = "",
    limit: int = 10,
) -> ToolChunk:
    """Query and filter the sales dataset.

    Args:
        category: Product category to filter. Empty means no filter.
        region: Region to filter. Empty means no filter.
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
    description = (
        "Compute summary statistics (count, total revenue, avg order value) "
        "for sales data, optionally grouped by a column."
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
            text = (
                f"Overall: {len(rows)} orders, "
                f"${total:,.2f} revenue, ${avg:,.2f} avg"
            )
            return ToolChunk(content=[TextBlock(text=text)])

        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(row.get(group_by, "?"), []).append(row)

        lines = [f"Summary by '{group_by}':"]
        for key in sorted(groups):
            g = groups[key]
            rev = sum(float(r["total"]) for r in g)
            lines.append(f"  {key}: {len(g)} orders, ${rev:,.2f}")
        return ToolChunk(content=[TextBlock(text="\n".join(lines))])


class GenerateChart(ToolBase):
    """Generate a chart from sales data using matplotlib."""

    name = "GenerateChart"
    description = (
        "Generate a bar/line/pie chart from sales data and save as PNG. "
        "Specify chart type, grouping column, and metric."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": ["bar", "line", "pie"],
                "description": "Type of chart to generate.",
            },
            "group_by": {
                "type": "string",
                "description": "Column to group data by.",
            },
            "metric": {
                "type": "string",
                "enum": ["revenue", "count"],
                "description": "Metric to visualize.",
            },
            "output_path": {
                "type": "string",
                "description": "File path to save the chart PNG.",
            },
        },
        "required": ["chart_type", "group_by", "metric", "output_path"],
    }
    is_concurrency_safe = True
    is_read_only = False

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Chart generation allowed.",
        )

    async def call(
        self,
        chart_type: str,
        group_by: str,
        metric: str,
        output_path: str,
    ) -> ToolChunk:
        rows = []
        with open(SALES_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)

        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(row.get(group_by, "?"), []).append(row)

        data = {}
        for key, g in sorted(groups.items()):
            if metric == "revenue":
                data[key] = sum(float(r["total"]) for r in g)
            else:
                data[key] = len(g)

        text = (
            f"[Simulated] Would generate {chart_type} chart:\n"
            f"  Group by: {group_by}\n"
            f"  Metric: {metric}\n"
            f"  Data points: {len(data)}\n"
            f"  Values: {data}\n"
            f"  Output: {output_path}\n"
            f"(matplotlib not required for this tutorial demo)"
        )
        return ToolChunk(content=[TextBlock(text=text)])


# =========================================================================
# Stream helper
# =========================================================================
async def stream_reply(agent: Agent, content: str) -> None:
    """Send a message and stream the reply with tool call indicators."""
    msg = UserMsg(name="user", content=content)
    print(f"\n[User]: {content[:100]}{'...' if len(content) > 100 else ''}")
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
    print("Tutorial 04: Tool Groups")
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

    # Define tool groups
    toolkit = Toolkit(
        # Basic group: always-active general tools
        tools=[Read(), Glob(), Grep()],
        # Named groups: activated on demand by the agent
        tool_groups=[
            ToolGroup(
                name="data_io",
                description=(
                    "Data reading and querying tools. Activate when the user "
                    "wants to explore, filter, or browse raw data."
                ),
                instructions=(
                    "Use query_sales for filtered searches. Use Read for "
                    "viewing raw file content."
                ),
                tools=[FunctionTool(query_sales, is_read_only=True)],
            ),
            ToolGroup(
                name="analysis",
                description=(
                    "Statistical analysis tools. Activate when the user wants "
                    "summaries, aggregations, trends, or computed metrics."
                ),
                instructions=(
                    "Use SalesSummary for quick aggregations. Use Bash to "
                    "run Python scripts for complex analysis."
                ),
                tools=[SalesSummary(), Bash()],
            ),
            ToolGroup(
                name="visualization",
                description=(
                    "Chart and visualization tools. Activate when the user "
                    "wants to create charts, plots, or visual reports."
                ),
                instructions=(
                    "Use GenerateChart to create standard chart types. "
                    "Specify chart_type, group_by, metric, and output_path."
                ),
                tools=[GenerateChart()],
            ),
        ],
    )

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a data analysis assistant. You have tool "
            "groups organized by function: data_io (reading/querying), "
            "analysis (statistics), and visualization (charts). Use the "
            "reset_tools meta tool to activate the right group for each task. "
            "Keep responses concise."
        ),
        model=model,
        toolkit=toolkit,
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    print(f"Agent: {agent.name}")
    print("Tool groups: basic (always on), data_io, analysis, visualization")

    # Task 1: Data exploration — should activate data_io group
    await stream_reply(
        agent,
        "First, I need to explore the sales data. Query the first 5 "
        "Electronics orders from the North region.",
    )

    # Task 2: Analysis — should activate analysis group
    await stream_reply(
        agent,
        "Now analyze the data: show me a summary grouped by category.",
    )

    # Task 3: Visualization — should activate visualization group
    await stream_reply(
        agent,
        "Great! Now create a bar chart showing revenue by category and "
        "save it to /tmp/revenue_by_category.png.",
    )

    print("\n" + "=" * 60)
    print("Tutorial 04 complete! Next: Tutorial 05 — MCP Integration")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
