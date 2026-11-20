# -*- coding: utf-8 -*-
"""Tutorial 07: Permission System — Control Agent behavior boundaries.

This tutorial demonstrates:
- Five PermissionMode options and their effects
- Configuring Allow, Deny, and Ask rules
- Permission evaluation priority order
- Switching modes at runtime
- DONT_ASK mode for unattended execution
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
from agentscope.model import ChatModelBase, DashScopeChatModel
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
    PermissionMode,
    PermissionRule,
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
OUTPUT_DIR = Path(__file__).resolve().parent / "output"


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
    """Read-only analytics tool with explicit permission declaration."""

    name = "SalesSummary"
    description = "Compute summary statistics for the sales dataset."
    input_schema = {
        "type": "object",
        "properties": {
            "group_by": {
                "type": "string",
                "description": "Column to group by (e.g. 'category', "
                "'region'). Empty for overall summary.",
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
# Stream helper
# =========================================================================
async def stream_reply(agent: Agent, content: str) -> None:
    """Send a message and stream the reply."""
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
# Example 1: EXPLORE mode (read-only)
# =========================================================================
async def example_explore_mode(model: ChatModelBase) -> None:
    """EXPLORE mode: read-only access, all modifications denied."""
    print("\n" + "=" * 60)
    print("Example 1: EXPLORE Mode (Read-Only)")
    print("=" * 60)
    print("  Mode: EXPLORE — only read-only tools are allowed")

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a data analysis assistant. Use tools to "
            "answer the user's questions. Keep responses concise."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[
                Read(),
                Glob(),
                Grep(),
                Bash(),
                SalesSummary(),
                FunctionTool(query_sales, is_read_only=True),
            ],
        ),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.EXPLORE,
            ),
        ),
    )

    # Read-only tools should work
    await stream_reply(
        agent,
        f"Read the first 5 lines of {SALES_CSV} and tell me what "
        "columns are available.",
    )

    # Write operations should be denied
    await stream_reply(
        agent,
        "Now create a file /tmp/test.txt with the text 'hello'.",
    )


# =========================================================================
# Example 2: Permission rules
# =========================================================================
async def example_permission_rules(model: ChatModelBase) -> None:
    """Configure Allow and Deny rules for fine-grained control."""
    print("\n" + "=" * 60)
    print("Example 2: Permission Rules (Allow + Deny)")
    print("=" * 60)

    context = PermissionContext(
        mode=PermissionMode.DEFAULT,
        allow_rules={
            "Bash": [
                PermissionRule(
                    tool_name="Bash",
                    rule_content="python",
                    behavior=PermissionBehavior.ALLOW,
                    source="tutorial",
                ),
                PermissionRule(
                    tool_name="Bash",
                    rule_content="cat",
                    behavior=PermissionBehavior.ALLOW,
                    source="tutorial",
                ),
            ],
        },
        deny_rules={
            "Bash": [
                PermissionRule(
                    tool_name="Bash",
                    rule_content="rm",
                    behavior=PermissionBehavior.DENY,
                    source="tutorial",
                ),
            ],
        },
    )

    print("  Rules configured:")
    print("    ALLOW: Bash commands containing 'python' or 'cat'")
    print("    DENY:  Bash commands containing 'rm'")
    print("    Other: Default ASK behavior")

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a data analysis assistant. Use Bash to run "
            "commands. Keep responses concise. "
            "If a tool call is denied, explain what happened."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[Bash(), Read(), Glob(), SalesSummary()],
        ),
        state=AgentState(permission_context=context),
    )

    # Allowed: python commands
    await stream_reply(
        agent,
        f"Run a Python one-liner to count the lines in {SALES_CSV}: "
        f"python3 -c \"print(sum(1 for _ in open('{SALES_CSV}')))\"",
    )

    # Denied: rm commands
    await stream_reply(
        agent,
        "Run: rm /tmp/test.txt",
    )


# =========================================================================
# Example 3: BYPASS mode (testing/sandbox)
# =========================================================================
async def example_bypass_mode(model: ChatModelBase) -> None:
    """BYPASS mode: skip ASK, while keeping explicit DENY decisions."""
    print("\n" + "=" * 60)
    print("Example 3: BYPASS Mode (Testing/Sandbox)")
    print("=" * 60)
    print("  Mode: BYPASS — skips ASK; explicit rules/tool DENY still apply")
    print("  WARNING: Only use in trusted environments!")

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse. Use the SalesSummary tool to analyze data. "
            "Keep responses concise."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[SalesSummary(), Read(), Glob()],
        ),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    await stream_reply(
        agent,
        "Show me a summary of the sales data grouped by region.",
    )


# =========================================================================
# Example 4: DONT_ASK mode (unattended)
# =========================================================================
async def example_dont_ask_mode(model: ChatModelBase) -> None:
    """DONT_ASK mode: converts ASK decisions to DENY."""
    print("\n" + "=" * 60)
    print("Example 4: DONT_ASK Mode (Unattended Execution)")
    print("=" * 60)
    print("  Mode: DONT_ASK — ASK decisions become DENY")
    print("  Use case: scheduled tasks, background jobs")

    context = PermissionContext(
        mode=PermissionMode.DONT_ASK,
        allow_rules={
            "Bash": [
                PermissionRule(
                    tool_name="Bash",
                    rule_content="python",
                    behavior=PermissionBehavior.ALLOW,
                    source="tutorial",
                ),
            ],
        },
    )

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse running in unattended mode. Use tools to "
            "answer questions. If a tool is denied, explain why and try "
            "an alternative approach. Keep responses concise."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[
                Bash(),
                Read(),
                Glob(),
                SalesSummary(),
            ],
        ),
        state=AgentState(permission_context=context),
    )

    # Explicitly allowed command works
    await stream_reply(
        agent,
        f'Run python3 -c "import csv; '
        f"r=csv.reader(open('{SALES_CSV}')); "
        f'print(next(r))" to show the CSV header.',
    )

    # Non-allowed commands are auto-denied (no prompt)
    await stream_reply(
        agent,
        "List the files in /tmp using ls -la.",
    )


# =========================================================================
# Example 5: Mode comparison summary
# =========================================================================
async def example_mode_comparison() -> None:
    """Summary of all permission modes."""
    print("\n" + "=" * 60)
    print("Example 5: Permission Mode Comparison")
    print("=" * 60)

    print(
        """
  ┌──────────────┬──────────┬──────────┬──────────┬────────────────┐
  │ Mode         │ Read     │ Write    │ Bash     │ Best For       │
  ├──────────────┼──────────┼──────────┼──────────┼────────────────┤
  │ DEFAULT      │ ASK*     │ ASK      │ varies   │ Interactive    │
  │ ACCEPT_EDITS │ ALLOW    │ ALLOW*   │ varies   │ Dev iteration  │
  │ EXPLORE      │ ALLOW    │ DENY     │ read-only│ Code browsing  │
  │ BYPASS       │ ALLOW*   │ ALLOW*   │ ALLOW*   │ Trusted sandbox│
  │ DONT_ASK     │ ASK→DENY │ ASK→DENY │ ASK→DENY │ Scheduled jobs │
  └──────────────┴──────────┴──────────┴──────────┴────────────────┘
  * ACCEPT_EDITS allows writes only within working directories
  * DEFAULT may accept a tool's explicit ALLOW decision
  * BYPASS still honors deny/ask rules and a tool's explicit DENY

  Common start: Deny rules → Ask rules → mode-specific policy
  EXPLORE:     read-only ALLOW, modification DENY
  BYPASS:      tool ASK is skipped, fallback ALLOW
  DONT_ASK:    every ASK path becomes DENY
""",
    )


# =========================================================================
# Main
# =========================================================================
async def main() -> None:
    print("Tutorial 07: Permission System")
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

    await example_explore_mode(model)
    await example_permission_rules(model)
    await example_bypass_mode(model)
    await example_dont_ask_mode(model)
    await example_mode_comparison()

    print("\n" + "=" * 60)
    print("Tutorial 07 complete! Next: Tutorial 08 — Human-in-the-Loop")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
