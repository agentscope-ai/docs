# -*- coding: utf-8 -*-
"""Tutorial 08: Human-in-the-Loop — Confirmation & external execution.

This tutorial demonstrates:
- Handling RequireUserConfirmEvent for tool call confirmation
- Building ConfirmResult with optional permission rules
- RequireExternalExecutionEvent for external tool execution
- Progressive trust via suggested_rules
- A terminal-based interactive confirmation UI
"""
# pylint: disable=missing-function-docstring,unused-argument
import asyncio
import csv
import os
from pathlib import Path
from typing import Any

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.event import (
    EventType,
    ConfirmResult,
    UserConfirmResultEvent,
    RequireUserConfirmEvent,
    RequireExternalExecutionEvent,
    ExternalExecutionResultEvent,
)
from agentscope.model import DashScopeChatModel
from agentscope.message import (
    UserMsg,
    TextBlock,
    ToolResultBlock,
    ToolResultState,
)
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
# External tool: simulates an action that requires external execution
# =========================================================================
class SendReport(ToolBase):
    """External tool that 'sends' a report via email."""

    name = "SendReport"
    description = (
        "Send an analysis report to a specified email address. "
        "This is an external tool — execution happens outside the Agent."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "recipient": {
                "type": "string",
                "description": "Email address of the recipient.",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line.",
            },
            "body": {
                "type": "string",
                "description": "Email body content.",
            },
        },
        "required": ["recipient", "subject", "body"],
    }
    is_concurrency_safe = True
    is_read_only = False
    is_external_tool = True

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="External tool, permission handled externally.",
        )

    async def call(self, **kwargs: Any) -> ToolChunk:
        raise RuntimeError("External tools should not be called directly.")


# =========================================================================
# Query tool (read-only, auto-allowed)
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


# =========================================================================
# Interactive event handler
# =========================================================================
async def handle_events_with_hitl(agent: Agent, content: str) -> None:
    """Process agent events with human-in-the-loop confirmation.

    This function demonstrates the complete HITL flow:
    1. Stream events from agent.reply_stream()
    2. When REQUIRE_USER_CONFIRM: prompt user and resume with confirmation
    3. When REQUIRE_EXTERNAL_EXECUTION: simulate external execution
    """
    msg = UserMsg(name="user", content=content)
    print(f"\n[User]: {content[:100]}{'...' if len(content) > 100 else ''}")
    print("\n[DataMuse]: ", end="", flush=True)

    async def process_stream(stream):
        """Process an event stream, handling HITL events recursively."""
        async for event in stream:
            match event.type:
                case EventType.TEXT_BLOCK_DELTA:
                    print(event.delta, end="", flush=True)

                case EventType.TOOL_CALL_START:
                    print(f"\n  >> Calling: {event.tool_call_name}")

                case EventType.TOOL_RESULT_END:
                    print(f"  >> Result: {event.state}")

                case EventType.REQUIRE_USER_CONFIRM:
                    await handle_user_confirm(agent, event)

                case EventType.REQUIRE_EXTERNAL_EXECUTION:
                    await handle_external_execution(agent, event)

                case EventType.REPLY_END:
                    print()

    await process_stream(agent.reply_stream(msg))


async def handle_user_confirm(
    agent: Agent,
    event: RequireUserConfirmEvent,
) -> None:
    """Handle a user confirmation request.

    Shows the pending tool calls and asks the user to confirm or deny each one.
    """
    print("\n" + "─" * 40)
    print("  CONFIRMATION REQUIRED")
    print("─" * 40)

    confirm_results = []
    for tool_call in event.tool_calls:
        print(f"  Tool: {tool_call.name}")
        print(f"  Input: {tool_call.input[:100]}...")

        if tool_call.suggested_rules:
            print("  Suggested rules:")
            for rule in tool_call.suggested_rules:
                print(
                    f"    → {rule.tool_name}: {rule.rule_content} "
                    f"({rule.behavior.value})",
                )

        # Auto-confirm for this tutorial (in a real app, ask the user)
        print("  → [Auto-confirming for tutorial demo]")
        confirmed = True

        if confirmed:
            confirm_results.append(
                ConfirmResult(
                    confirmed=True,
                    tool_call=tool_call,
                    rules=tool_call.suggested_rules or None,
                ),
            )
        else:
            confirm_results.append(
                ConfirmResult(
                    confirmed=False,
                    tool_call=tool_call,
                ),
            )

    print("─" * 40)

    # Resume agent with confirmation results
    confirm_event = UserConfirmResultEvent(
        reply_id=event.reply_id,
        confirm_results=confirm_results,
    )

    async for evt in agent.reply_stream(confirm_event):
        match evt.type:
            case EventType.TEXT_BLOCK_DELTA:
                print(evt.delta, end="", flush=True)
            case EventType.TOOL_CALL_START:
                print(f"\n  >> Calling: {evt.tool_call_name}")
            case EventType.TOOL_RESULT_END:
                print(f"  >> Result: {evt.state}")
            case EventType.REQUIRE_USER_CONFIRM:
                await handle_user_confirm(agent, evt)
            case EventType.REQUIRE_EXTERNAL_EXECUTION:
                await handle_external_execution(agent, evt)
            case EventType.REPLY_END:
                print()


async def handle_external_execution(
    agent: Agent,
    event: RequireExternalExecutionEvent,
) -> None:
    """Handle an external execution request.

    Simulates executing the tool externally and returning results.
    """
    print("\n" + "─" * 40)
    print("  EXTERNAL EXECUTION")
    print("─" * 40)

    execution_results = []
    for tool_call in event.tool_calls:
        print(f"  Tool: {tool_call.name}")
        print(f"  Input: {tool_call.input[:100]}...")
        print("  → [Simulating external execution...]")

        # Simulate external execution result
        result = ToolResultBlock(
            id=tool_call.id,
            name=tool_call.name,
            output=f"[External] Successfully executed {tool_call.name}. "
            f"Report sent to the specified recipient.",
            state=ToolResultState.SUCCESS,
        )
        execution_results.append(result)

    print("─" * 40)

    # Resume agent with execution results
    exec_event = ExternalExecutionResultEvent(
        reply_id=event.reply_id,
        execution_results=execution_results,
    )

    async for evt in agent.reply_stream(exec_event):
        match evt.type:
            case EventType.TEXT_BLOCK_DELTA:
                print(evt.delta, end="", flush=True)
            case EventType.TOOL_CALL_START:
                print(f"\n  >> Calling: {evt.tool_call_name}")
            case EventType.TOOL_RESULT_END:
                print(f"  >> Result: {evt.state}")
            case EventType.REQUIRE_USER_CONFIRM:
                await handle_user_confirm(agent, evt)
            case EventType.REQUIRE_EXTERNAL_EXECUTION:
                await handle_external_execution(agent, evt)
            case EventType.REPLY_END:
                print()


# =========================================================================
# Example 1: User confirmation flow
# =========================================================================
async def example_user_confirmation(model) -> None:
    """Demonstrate the user confirmation flow."""
    print("\n" + "=" * 60)
    print("Example 1: User Confirmation (ASK → Confirm)")
    print("=" * 60)
    print("  Mode: DEFAULT — Bash commands require confirmation")

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a data analysis assistant. Use tools to "
            "answer questions. Keep responses concise."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[
                Bash(),
                Read(),
                Glob(),
                Grep(),
                FunctionTool(query_sales, is_read_only=True),
            ],
        ),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.DEFAULT,
            ),
        ),
    )

    # This should trigger a user confirmation for the Bash tool
    await handle_events_with_hitl(
        agent,
        f"Count the number of lines in {SALES_CSV} using the wc command.",
    )


# =========================================================================
# Example 2: External tool execution
# =========================================================================
async def example_external_execution(model) -> None:
    """Demonstrate the external tool execution flow."""
    print("\n" + "=" * 60)
    print("Example 2: External Tool Execution")
    print("=" * 60)
    print("  SendReport is an external tool — Agent yields, we execute")

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a data analysis assistant. You can send "
            "analysis reports via the SendReport tool. "
            "Keep responses concise."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[
                Read(),
                FunctionTool(query_sales, is_read_only=True),
                SendReport(),
            ],
        ),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    await handle_events_with_hitl(
        agent,
        "Send a brief sales summary report to analyst@example.com "
        "with subject 'Weekly Sales Report'.",
    )


# =========================================================================
# Example 3: HITL flow diagram
# =========================================================================
async def example_flow_diagram() -> None:
    """Display the HITL interaction flow."""
    print("\n" + "=" * 60)
    print("Example 3: HITL Interaction Flows")
    print("=" * 60)

    print(
        """
  Flow 1: User Confirmation
  ─────────────────────────
  reply_stream(UserMsg)
    │
    ├─ TEXT_BLOCK_DELTA ──── stream text to UI
    ├─ TOOL_CALL_START ───── show tool being called
    │
    ├─ REQUIRE_USER_CONFIRM ← Agent pauses here
    │   │
    │   ├─ Show tool_calls to user
    │   ├─ User confirms/denies
    │   └─ Build UserConfirmResultEvent
    │       │
    │       └─ reply_stream(confirm_event)
    │           ├─ TOOL_RESULT_END ─── tool executed (if confirmed)
    │           ├─ TEXT_BLOCK_DELTA ── continue streaming
    │           └─ REPLY_END ──────── done
    │
    └─ REPLY_END (if no confirmation needed)

  Flow 2: External Execution
  ──────────────────────────
  reply_stream(UserMsg)
    │
    ├─ REQUIRE_EXTERNAL_EXECUTION ← Agent pauses here
    │   │
    │   ├─ Extract tool_calls
    │   ├─ Execute externally (API call, human action, etc.)
    │   ├─ Build ToolResultBlock for each
    │   └─ Build ExternalExecutionResultEvent
    │       │
    │       └─ reply_stream(exec_event)
    │           ├─ TEXT_BLOCK_DELTA ── Agent processes results
    │           └─ REPLY_END ──────── done

  Progressive Trust (Suggested Rules)
  ────────────────────────────────────
  When confirming, you can accept suggested_rules:

    ConfirmResult(
        confirmed=True,
        tool_call=tc,
        rules=tc.suggested_rules,  ← Accept rules
    )

  This adds Allow rules to PermissionContext, so similar
  operations are auto-allowed in future calls.
""",
    )


# =========================================================================
# Main
# =========================================================================
async def main() -> None:
    print("Tutorial 08: Human-in-the-Loop")
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

    # Example 1: User confirmation
    await example_user_confirmation(model)

    # Example 2: External tool execution
    await example_external_execution(model)

    # Example 3: Flow diagram
    await example_flow_diagram()

    print("\n" + "=" * 60)
    print("Tutorial 08 complete! Next: Tutorial 09 — Streaming UI")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
