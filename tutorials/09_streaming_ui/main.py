# -*- coding: utf-8 -*-
"""Tutorial 09: Streaming UI — Build a real-time interactive terminal UI.

This tutorial demonstrates:
- Handling all event types from reply_stream
- Token usage tracking via ModelCallEndEvent
- Thinking block visualization
- Tool call progress indicators
- Building a complete event-driven terminal UI
"""
# pylint: disable=missing-function-docstring,unused-argument
import asyncio
import csv
import os
import time
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
    Read,
    Glob,
    Grep,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SALES_CSV = DATA_DIR / "sales_data.csv"


# =========================================================================
# Custom tools
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


# =========================================================================
# Streaming UI
# =========================================================================
async def streaming_ui(agent: Agent, content: str) -> dict:
    """Full-featured streaming UI with event tracking.

    Returns a stats dict with token counts and event counts.
    """
    msg = UserMsg(name="user", content=content)

    stats = {
        "input_tokens": 0,
        "output_tokens": 0,
        "model_calls": 0,
        "tool_calls": 0,
        "text_blocks": 0,
        "data_blocks": 0,
        "thinking_blocks": 0,
        "events": 0,
    }
    model_call_start_time = None

    print(f"\n{'─' * 50}")
    print(f"  [User]: {content[:80]}{'...' if len(content) > 80 else ''}")
    print(f"{'─' * 50}")

    async for event in agent.reply_stream(msg):
        stats["events"] += 1

        match event.type:
            # --- Reply lifecycle ---
            case EventType.REPLY_START:
                print(f"\n  [{event.name}]:", end="", flush=True)

            case EventType.REPLY_END:
                print()

            # --- Model calls ---
            case EventType.MODEL_CALL_START:
                model_call_start_time = time.time()
                stats["model_calls"] += 1

            case EventType.MODEL_CALL_END:
                elapsed = (
                    time.time() - model_call_start_time
                    if model_call_start_time
                    else 0
                )
                stats["input_tokens"] += event.input_tokens
                stats["output_tokens"] += event.output_tokens
                print(
                    f"\n  [model] {event.input_tokens}in "
                    f"+ {event.output_tokens}out "
                    f"({elapsed:.1f}s)",
                    end="",
                    flush=True,
                )
                model_call_start_time = None

            # --- Text blocks ---
            case EventType.TEXT_BLOCK_START:
                stats["text_blocks"] += 1
                print("\n  ", end="", flush=True)

            case EventType.TEXT_BLOCK_DELTA:
                print(event.delta, end="", flush=True)

            case EventType.TEXT_BLOCK_END:
                pass

            # --- Data blocks (image/audio/file payloads) ---
            case EventType.DATA_BLOCK_START:
                stats["data_blocks"] += 1
                print(
                    f"\n  [data] receiving {event.media_type}",
                    end="",
                    flush=True,
                )

            case EventType.DATA_BLOCK_DELTA:
                pass  # do not print base64 payloads in a terminal UI

            case EventType.DATA_BLOCK_END:
                print(" [received]", end="", flush=True)

            # --- Thinking blocks ---
            case EventType.THINKING_BLOCK_START:
                stats["thinking_blocks"] += 1
                print("\n  [thinking] ", end="", flush=True)

            case EventType.THINKING_BLOCK_DELTA:
                # Show abbreviated thinking
                text = event.delta.replace("\n", " ")
                if len(text) > 60:
                    text = text[:60] + "..."
                print(text, end="", flush=True)

            case EventType.THINKING_BLOCK_END:
                print()

            # --- One-shot context hint ---
            case EventType.HINT_BLOCK:
                hint = str(event.hint).replace("\n", " ")
                if len(hint) > 80:
                    hint = hint[:80] + "..."
                print(
                    f"\n  [hint from {event.source or 'system'}] {hint}",
                    end="",
                    flush=True,
                )

            # --- Tool calls ---
            case EventType.TOOL_CALL_START:
                stats["tool_calls"] += 1
                print(
                    f"\n  [tool] >> {event.tool_call_name}",
                    end="",
                    flush=True,
                )

            case EventType.TOOL_CALL_DELTA:
                pass  # suppress raw JSON fragments

            case EventType.TOOL_CALL_END:
                pass

            # --- Tool results ---
            case EventType.TOOL_RESULT_START:
                print(" (executing...)", end="", flush=True)

            case EventType.TOOL_RESULT_TEXT_DELTA:
                pass  # suppress verbose tool output

            case EventType.TOOL_RESULT_DATA_DELTA:
                pass  # a graphical UI could render event.data or event.url

            case EventType.TOOL_RESULT_END:
                state_icon = "ok" if event.state == "success" else event.state
                print(f" [{state_icon}]", end="", flush=True)

            # --- HITL ---
            case EventType.REQUIRE_USER_CONFIRM:
                print(
                    f"\n  [hitl] Confirmation required for "
                    f"{len(event.tool_calls)} tool(s)",
                )

            case EventType.REQUIRE_EXTERNAL_EXECUTION:
                print(
                    f"\n  [hitl] External execution for "
                    f"{len(event.tool_calls)} tool(s)",
                )

            # These events are normally passed back into reply_stream() to
            # resume a parked reply, rather than emitted by a normal run.
            case EventType.USER_CONFIRM_RESULT:
                print("\n  [resume] User confirmation received")

            case EventType.EXTERNAL_EXECUTION_RESULT:
                print("\n  [resume] External execution result received")

            case EventType.USER_INTERRUPT:
                print("\n  [interrupt] User stopped the parked reply")

            # --- Service/application extension event ---
            case EventType.CUSTOM:
                print(
                    f"\n  [custom:{event.name}] {event.value}",
                    end="",
                    flush=True,
                )

            # --- Max iterations ---
            case EventType.EXCEED_MAX_ITERS:
                print("\n  [warn] Max iterations exceeded!")

            case _:
                print(f"\n  [event] {event.type}", end="", flush=True)

    # Print summary
    print(f"\n{'─' * 50}")
    print("  Stats:")
    print(
        f"    Tokens: {stats['input_tokens']} in "
        f"+ {stats['output_tokens']} out "
        f"= {stats['input_tokens'] + stats['output_tokens']} total",
    )
    print(
        f"    Model calls: {stats['model_calls']} | "
        f"Tool calls: {stats['tool_calls']}",
    )
    print(
        f"    Text blocks: {stats['text_blocks']} | "
        f"Data blocks: {stats['data_blocks']} | "
        f"Thinking blocks: {stats['thinking_blocks']}",
    )
    print(f"    Total events: {stats['events']}")
    print(f"{'─' * 50}")

    return stats


# =========================================================================
# Examples
# =========================================================================
async def example_basic_streaming(agent: Agent) -> None:
    """Basic streaming with all event types visible."""
    print("\n" + "=" * 60)
    print("Example 1: Basic Streaming UI")
    print("=" * 60)

    await streaming_ui(
        agent,
        f"Read the first 3 lines of {SALES_CSV}, then use SalesSummary "
        f"to show a summary grouped by category.",
    )


async def example_multi_turn(agent: Agent) -> None:
    """Multi-turn conversation showing cumulative token tracking."""
    print("\n" + "=" * 60)
    print("Example 2: Multi-Turn Token Tracking")
    print("=" * 60)

    total_tokens = {"input": 0, "output": 0}

    for i, question in enumerate(
        [
            "What categories are in the sales data? Use query_sales "
            "with limit=3.",
            "Now show me the summary grouped by region.",
        ],
        1,
    ):
        print(f"\n  Turn {i}:")
        stats = await streaming_ui(agent, question)
        total_tokens["input"] += stats["input_tokens"]
        total_tokens["output"] += stats["output_tokens"]

    print(f"\n  Cumulative tokens across {2} turns:")
    print(
        f"    Input: {total_tokens['input']} | "
        f"Output: {total_tokens['output']} | "
        f"Total: {total_tokens['input'] + total_tokens['output']}",
    )


async def example_event_catalog() -> None:
    """Display all event types organized by category."""
    print("\n" + "=" * 60)
    print("Example 3: Event Type Catalog")
    print("=" * 60)

    print(
        """
  All AgentScope Event Types:
  ───────────────────────────

  Reply Lifecycle        Model Calls           Text Blocks
  ├─ REPLY_START         ├─ MODEL_CALL_START   ├─ TEXT_BLOCK_START
  └─ REPLY_END           └─ MODEL_CALL_END     ├─ TEXT_BLOCK_DELTA
                           (tokens tracking)    └─ TEXT_BLOCK_END

  Thinking Blocks        Tool Calls            Tool Results
  ├─ THINKING_..._START  ├─ TOOL_CALL_START    ├─ TOOL_RESULT_START
  ├─ THINKING_..._DELTA  ├─ TOOL_CALL_DELTA    ├─ TOOL_RESULT_TEXT_DELTA
  └─ THINKING_..._END    └─ TOOL_CALL_END      ├─ TOOL_RESULT_DATA_DELTA
                                                └─ TOOL_RESULT_END

  Data Blocks            HITL Events           Other
  ├─ DATA_BLOCK_START    ├─ REQUIRE_USER_      └─ EXCEED_MAX_ITERS
  ├─ DATA_BLOCK_DELTA    │  CONFIRM
  └─ DATA_BLOCK_END      ├─ REQUIRE_EXTERNAL_
                          │  EXECUTION
                          ├─ USER_CONFIRM_
                          │  RESULT
                          └─ EXTERNAL_EXECUTION_
                             RESULT

  Lifecycle pattern: START → DELTA(s) → END
  Each event has: id, created_at, type, reply_id
  ModelCallEnd adds: input_tokens, output_tokens
  ToolResultEnd adds: state (success/error/denied/interrupted)
""",
    )


# =========================================================================
# Main
# =========================================================================
async def main() -> None:
    print("Tutorial 09: Streaming UI")
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
            "You are DataMuse, a data analysis assistant. Use tools to "
            "answer questions about the sales data. Keep responses concise."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[
                Read(),
                Glob(),
                Grep(),
                FunctionTool(query_sales, is_read_only=True),
                SalesSummary(),
            ],
        ),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    await example_basic_streaming(agent)
    await example_multi_turn(agent)
    await example_event_catalog()

    print("\n" + "=" * 60)
    print("Tutorial 09 complete! Next: Tutorial 10 — Context Management")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
