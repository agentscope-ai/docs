# -*- coding: utf-8 -*-
"""Tutorial 16: Shared tools for both main.py (CLI) and serve.py (Web UI).

By extracting tool definitions here, the two run modes consume the exact same
SalesProfile / SalesBreakdown / ReportWriter implementations and any tweak
shows up in both flows automatically.
"""
# pylint: disable=missing-function-docstring,unused-argument
import csv
import os
import re
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Callable

from agentscope.agent import Agent
from agentscope.message import TextBlock
from agentscope.middleware import MiddlewareBase
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
)
from agentscope.tool import ToolBase, ToolChunk


TUTORIAL_DIR = Path(__file__).resolve().parent
DATA_DIR = TUTORIAL_DIR.parent / "data"
SALES_CSV = DATA_DIR / "sales_data.csv"
WORKSPACE_DIR = TUTORIAL_DIR / "workspace"
REPORTS_DIR = WORKSPACE_DIR / "reports"


def create_model():
    """Create a chat model from available API keys."""
    if os.environ.get("DASHSCOPE_API_KEY"):
        from agentscope.credential import DashScopeCredential
        from agentscope.model import DashScopeChatModel

        return DashScopeChatModel(
            credential=DashScopeCredential(
                api_key=os.environ["DASHSCOPE_API_KEY"],
            ),
            model="qwen-plus",
        )

    if os.environ.get("OPENAI_API_KEY"):
        from agentscope.credential import OpenAICredential
        from agentscope.model import OpenAIChatModel

        return OpenAIChatModel(
            credential=OpenAICredential(
                api_key=os.environ["OPENAI_API_KEY"],
            ),
            model="gpt-4o",
        )

    raise EnvironmentError(
        "No API key found. Set DASHSCOPE_API_KEY or OPENAI_API_KEY.",
    )


def _load_rows() -> list[dict[str, str]]:
    with open(SALES_CSV, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _money(value: float) -> str:
    return f"${value:,.2f}"


class SalesProfile(ToolBase):
    """Inspect the sales CSV and return schema plus basic quality checks."""

    name = "SalesProfile"
    description = (
        "Inspect the sales dataset and return row count, columns, date range, "
        "missing value counts, and a few sample rows."
    )
    input_schema = {"type": "object", "properties": {}, "required": []}
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="SalesProfile is read-only.",
        )

    async def call(self) -> ToolChunk:
        rows = _load_rows()
        columns = list(rows[0].keys()) if rows else []
        missing = {
            col: sum(1 for row in rows if row.get(col, "") == "")
            for col in columns
        }
        dates = sorted(row["date"] for row in rows)
        sample = rows[:3]

        lines = [
            "Sales data profile",
            f"- file: {SALES_CSV}",
            f"- rows: {len(rows)}",
            f"- columns: {', '.join(columns)}",
            f"- date range: {dates[0]} to {dates[-1]}" if dates else "",
            "- missing values:",
        ]
        lines.extend(f"  - {col}: {count}" for col, count in missing.items())
        lines.append("- sample rows:")
        lines.extend(f"  - {row}" for row in sample)

        return ToolChunk(content=[TextBlock(text="\n".join(lines))])


class SalesBreakdown(ToolBase):
    """Compute revenue and order breakdowns by a selected dimension."""

    name = "SalesBreakdown"
    description = (
        "Compute order count, revenue, and average order value grouped by "
        "category, region, payment_method, or customer_tier."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "group_by": {
                "type": "string",
                "description": (
                    "Dimension to group by: category, region, payment_method, "
                    "or customer_tier."
                ),
            },
        },
        "required": ["group_by"],
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
            message="SalesBreakdown is read-only.",
        )

    async def call(self, group_by: str) -> ToolChunk:
        rows = _load_rows()
        allowed = {"category", "region", "payment_method", "customer_tier"}
        if group_by not in allowed:
            return ToolChunk(
                content=[
                    TextBlock(
                        text=(
                            f"Unsupported group_by={group_by!r}. "
                            f"Choose one of: {', '.join(sorted(allowed))}."
                        ),
                    ),
                ],
            )

        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            groups.setdefault(row[group_by], []).append(row)

        total_revenue = sum(float(row["total"]) for row in rows)
        lines = [
            f"Sales breakdown by {group_by}",
            "group | orders | revenue | revenue_share | avg_order",
            "--- | ---: | ---: | ---: | ---:",
        ]
        for key, group_rows in sorted(
            groups.items(),
            key=lambda item: sum(float(row["total"]) for row in item[1]),
            reverse=True,
        ):
            revenue = sum(float(row["total"]) for row in group_rows)
            share = revenue / total_revenue if total_revenue else 0
            avg = revenue / len(group_rows) if group_rows else 0
            lines.append(
                f"{key} | {len(group_rows)} | {_money(revenue)} | "
                f"{share:.1%} | {_money(avg)}",
            )

        return ToolChunk(content=[TextBlock(text="\n".join(lines))])


class ReportWriter(ToolBase):
    """Write a Markdown analysis report into the tutorial workspace."""

    name = "ReportWriter"
    description = (
        "Write the final sales analysis report to the local workspace. "
        "Use this only after analysis is complete."
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
                "description": "Optional Markdown filename.",
                "default": "sales_analysis_report.md",
            },
        },
        "required": ["title", "markdown"],
    }
    is_concurrency_safe = False
    is_read_only = False

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            message="ReportWriter writes a file into the workspace.",
        )

    async def call(
        self,
        title: str,
        markdown: str,
        filename: str = "sales_analysis_report.md",
    ) -> ToolChunk:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename).strip("._")
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        path = REPORTS_DIR / safe_name
        content = f"# {title}\n\n{markdown.strip()}\n"
        path.write_text(content, encoding="utf-8")

        return ToolChunk(
            content=[
                TextBlock(
                    text=f"Report written successfully: {path}",
                ),
            ],
        )


class ConsoleTraceMiddleware(MiddlewareBase):
    """Print per-turn timing to the console without changing behavior."""

    async def on_reply(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[[], AsyncGenerator],
    ) -> AsyncGenerator:
        started = time.perf_counter()
        print(f"\n[trace] reply started: agent={agent.name}")
        async for item in next_handler():
            yield item
        elapsed = time.perf_counter() - started
        print(f"\n[trace] reply finished in {elapsed:.2f}s")


class TimingMiddleware(MiddlewareBase):
    """ConsoleTraceMiddleware with quieter server-side output."""

    async def on_reply(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[[], AsyncGenerator],
    ) -> AsyncGenerator:
        started = time.perf_counter()
        async for item in next_handler():
            yield item
        elapsed = time.perf_counter() - started
        print(f"  [timing] reply finished in {elapsed:.2f}s")
