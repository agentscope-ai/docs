# -*- coding: utf-8 -*-
"""Tutorial 15: Multi-Agent — Collaborative agent teams.

This tutorial demonstrates:
- Multiple specialized agents working together
- observe() for context injection without triggering reasoning
- Sequential pipeline pattern (Collector → Analyst → Writer)
- Parallel branch pattern with asyncio.gather
- Message passing between agents
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
from agentscope.message import UserMsg, AssistantMsg, TextBlock
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
# Tools
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
        for row in csv.DictReader(f):
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
        "Compute summary statistics (count, total revenue, avg) for the "
        "sales dataset, optionally grouped by a column."
    )
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
# Stream + print helper
# =========================================================================
async def agent_reply(agent: Agent, content: str) -> str:
    """Send a message to an agent, stream events, return text response."""
    msg = UserMsg(name="user", content=content)
    print(f"\n  [{agent.name}] Processing...", end="", flush=True)

    text_parts = []
    async for event in agent.reply_stream(msg):
        match event.type:
            case EventType.TEXT_BLOCK_DELTA:
                text_parts.append(event.delta)
            case EventType.TOOL_CALL_START:
                print(f"\n    >> {event.tool_call_name}", end="", flush=True)
            case EventType.TOOL_RESULT_END:
                print(f" [{event.state}]", end="", flush=True)
            case EventType.REPLY_END:
                pass

    text = "".join(text_parts)
    preview = text[:120].replace("\n", " ")
    print(f"\n  [{agent.name}] Done: {preview}...")
    return text


# =========================================================================
# Agent factory
# =========================================================================
def create_agents(model):
    """Create the three-agent DataMuse team."""
    bypass = AgentState(
        permission_context=PermissionContext(
            mode=PermissionMode.BYPASS,
        ),
    )

    collector = Agent(
        name="DataMuse_Collector",
        system_prompt=(
            "You are DataMuse_Collector, a member of the DataMuse team. "
            "Your role is gathering raw sales data using query tools and "
            "presenting it clearly with numbers. Stay focused on data — no "
            "analysis or recommendations. Downstream teammates "
            "(DataMuse_Analyst, DataMuse_Writer) will turn your output into "
            "the final report."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[
                Read(),
                Glob(),
                Grep(),
                FunctionTool(query_sales, is_read_only=True),
            ],
        ),
        state=bypass,
    )

    analyst = Agent(
        name="DataMuse_Analyst",
        system_prompt=(
            "You are DataMuse_Analyst, a member of the DataMuse team. "
            "DataMuse_Collector hands you raw rows; you compute insights — "
            "trends, comparisons, rankings, anomalies — using SalesSummary "
            "for aggregations. Provide specific numbers and percentages, "
            "and keep responses concise so DataMuse_Writer can turn them "
            "into a report."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[SalesSummary(), Bash()],
        ),
        state=bypass,
    )

    writer = Agent(
        name="DataMuse_Writer",
        system_prompt=(
            "You are DataMuse_Writer, the report-writing member of the "
            "DataMuse team. DataMuse_Analyst hands you analysis results; "
            "you turn them into clear, structured markdown summaries with "
            "key findings and actionable insights. Keep reports brief "
            "(under 200 words)."
        ),
        model=model,
        toolkit=Toolkit(tools=[]),
        state=bypass,
    )

    return collector, analyst, writer


# =========================================================================
# Example 1: Sequential pipeline
# =========================================================================
async def example_sequential_pipeline(model) -> None:
    """Three agents in a sequential pipeline."""
    print("\n" + "=" * 60)
    print("Example 1: Sequential Pipeline")
    print("  User → DataMuse_Collector → DataMuse_Analyst → DataMuse_Writer")
    print("=" * 60)

    collector, analyst, writer = create_agents(model)

    # Step 1: Collector gathers data
    print("\n  Step 1: DataMuse_Collector gathers data")
    collected_data = await agent_reply(
        collector,
        "Collect sales data: query 10 Electronics orders and 10 "
        "Clothing orders. Show all records.",
    )

    # Step 2: Analyst receives data and analyzes
    print(
        "\n  Step 2: DataMuse_Analyst analyzes (receives collector's output)",
    )
    # Use observe() to inject the collector's output as context
    collector_msg = AssistantMsg(
        name="DataMuse_Collector",
        content=collected_data,
    )
    await analyst.observe(collector_msg)

    analysis = await agent_reply(
        analyst,
        "Based on the collected data above, compare Electronics vs "
        "Clothing: which has higher revenue? Use SalesSummary grouped "
        "by category for precise numbers.",
    )

    # Step 3: Writer receives analysis and creates report
    print("\n  Step 3: DataMuse_Writer creates final report")
    analyst_msg = AssistantMsg(
        name="DataMuse_Analyst",
        content=analysis,
    )
    await writer.observe(analyst_msg)

    report = await agent_reply(
        writer,
        "Write a brief analysis report based on the data analysis above. "
        "Include key findings and one recommendation.",
    )

    print("\n" + "─" * 40)
    print("  Final Report:")
    print("─" * 40)
    print(report)


# =========================================================================
# Example 2: Parallel branches
# =========================================================================
async def example_parallel_branches(model) -> None:
    """Two analysts work in parallel, then results are merged."""
    print("\n" + "=" * 60)
    print("Example 2: Parallel Branches")
    print("  Collector → [Analyst A, Analyst B] → Writer")
    print("=" * 60)

    collector, _, writer = create_agents(model)

    # Create two specialized analysts
    bypass = AgentState(
        permission_context=PermissionContext(
            mode=PermissionMode.BYPASS,
        ),
    )

    region_analyst = Agent(
        name="DataMuse_RegionAnalyst",
        system_prompt=(
            "You are DataMuse_RegionAnalyst, a parallel-branch member of "
            "the DataMuse team. Analyze sales data by region — identify the "
            "top and bottom performing regions, with specific numbers. "
            "DataMuse_Writer will merge your output with "
            "DataMuse_CategoryAnalyst's."
        ),
        model=model,
        toolkit=Toolkit(tools=[SalesSummary()]),
        state=bypass,
    )

    category_analyst = Agent(
        name="DataMuse_CategoryAnalyst",
        system_prompt=(
            "You are DataMuse_CategoryAnalyst, a parallel-branch member of "
            "the DataMuse team. Analyze sales data by category — identify "
            "the top and bottom performing categories, with specific "
            "numbers. DataMuse_Writer will merge your output with "
            "DataMuse_RegionAnalyst's."
        ),
        model=model,
        toolkit=Toolkit(tools=[SalesSummary()]),
        state=bypass,
    )

    # Step 1: Collect data
    print("\n  Step 1: Collect data")
    data = await agent_reply(
        collector,
        f"Read the first 5 lines of {SALES_CSV} to show the data "
        "structure.",
    )

    # Step 2: Two analysts work in parallel
    print("\n  Step 2: Two analysts work in parallel")
    data_msg = AssistantMsg(name="DataMuse_Collector", content=data)
    await region_analyst.observe(data_msg)
    await category_analyst.observe(data_msg)

    region_result, category_result = await asyncio.gather(
        agent_reply(
            region_analyst,
            "Analyze sales by region using SalesSummary. Which region "
            "performs best?",
        ),
        agent_reply(
            category_analyst,
            "Analyze sales by category using SalesSummary. Which "
            "category has the highest revenue?",
        ),
    )

    # Step 3: Writer merges results
    print("\n  Step 3: Writer merges parallel results")
    await writer.observe(
        AssistantMsg(name="DataMuse_RegionAnalyst", content=region_result),
    )
    await writer.observe(
        AssistantMsg(name="DataMuse_CategoryAnalyst", content=category_result),
    )

    report = await agent_reply(
        writer,
        "Combine the region analysis and category analysis above "
        "into a unified summary. Highlight the top performers.",
    )

    print("\n" + "─" * 40)
    print("  Merged Report:")
    print("─" * 40)
    print(report)


# =========================================================================
# Example 3: Architecture overview
# =========================================================================
async def example_architecture() -> None:
    """Display multi-agent architecture patterns."""
    print("\n" + "=" * 60)
    print("Example 3: Multi-Agent Architecture Patterns")
    print("=" * 60)

    print(
        """
  Key Methods:
  ────────────
  reply(msg)    → Triggers reasoning + acting, returns response
  observe(msg)  → Injects message into context (no reasoning)

  Pattern 1: Sequential Pipeline
  ───────────────────────────────
  data = await collector.reply(user_msg)

  await analyst.observe(data_as_msg)        # inject context
  analysis = await analyst.reply(task_msg)  # then reason

  await writer.observe(analysis_as_msg)
  report = await writer.reply(task_msg)

  Pattern 2: Parallel Branches
  ────────────────────────────
  data = await collector.reply(user_msg)

  await analyst_a.observe(data)
  await analyst_b.observe(data)

  result_a, result_b = await asyncio.gather(
      analyst_a.reply(task_a),
      analyst_b.reply(task_b),
  )

  await summarizer.observe(result_a)
  await summarizer.observe(result_b)
  summary = await summarizer.reply(merge_task)

  Pattern 3: Dynamic Routing
  ──────────────────────────
  routing = await router.reply(user_msg)
  target = parse_route(routing)

  if target == "simple":
      result = await fast_agent.reply(user_msg)
  else:
      result = await thorough_agent.reply(user_msg)

  Design Principles:
  ──────────────────
  • Each agent has a focused role and minimal tools
  • Use observe() for context sharing (no unnecessary reasoning)
  • Python code IS the orchestration (no framework needed)
  • Parallel branches with asyncio.gather for speed
""",
    )


# =========================================================================
# Main
# =========================================================================
async def main() -> None:
    print("Tutorial 15: Multi-Agent Collaboration")
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

    # Example 1: Sequential pipeline
    await example_sequential_pipeline(model)

    # Example 2: Parallel branches
    await example_parallel_branches(model)

    # Example 3: Architecture overview
    await example_architecture()

    print("\n" + "=" * 60)
    print("Tutorial 15 complete! Next: Tutorial 16 — Complete DataMuse")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
