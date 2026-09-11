# -*- coding: utf-8 -*-
"""Tutorial 06: Skills — Extend Agent abilities with Markdown instructions.

This tutorial demonstrates:
- Creating SKILL.md files with frontmatter metadata
- Loading skills with LocalSkillLoader
- How the Skill tool is exposed when skills are available
- Combining skills with ToolGroups
- Agent reading and following skill instructions
"""
# pylint: disable=missing-function-docstring
import asyncio
import os
from pathlib import Path

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.event import EventType
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.skill import LocalSkillLoader
from agentscope.state import AgentState
from agentscope.tool import (
    Toolkit,
    ToolGroup,
    Bash,
    Read,
    Glob,
    Grep,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SALES_CSV = DATA_DIR / "sales_data.csv"
SKILLS_DIR = Path(__file__).resolve().parent / "skills"


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
# Example 1: Skills in the basic group
# =========================================================================
async def example_basic_skills(model) -> None:
    """Load skills into the basic group (always available)."""
    print("\n" + "=" * 60)
    print("Example 1: Skills in the Basic Group")
    print("=" * 60)

    # Load all skills from the skills directory
    skill_loader = LocalSkillLoader(
        directory=str(SKILLS_DIR),
        scan_subdir=True,
    )

    # List what skills are available
    skills = await skill_loader.list_skills()
    print(f"  Found {len(skills)} skills:")
    for skill in skills:
        print(f"    - {skill.name}: {skill.description[:60]}...")

    # Create agent with skills in basic group
    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a data analysis assistant with skills for "
            "generating charts and writing reports. When the user asks you "
            "to create a chart or write a report, use the Skill tool to "
            "read the skill instructions first, then follow them. "
            "Keep responses concise."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[Read(), Bash(), Glob(), Grep()],
            skills_or_loaders=[skill_loader],
        ),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    # The agent should read the skill, then use Bash to execute Python
    await stream_reply(
        agent,
        f"I want to create a bar chart showing the number of orders per "
        f"region from {SALES_CSV}. Use the chart_generator skill to guide "
        f"your approach. Save the chart to /tmp/orders_by_region.png.",
    )


# =========================================================================
# Example 2: Skills in ToolGroups
# =========================================================================
async def example_skills_in_groups(model) -> None:
    """Organize skills into ToolGroups for on-demand activation."""
    print("\n" + "=" * 60)
    print("Example 2: Skills in ToolGroups")
    print("=" * 60)

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a data analysis assistant. You have tool "
            "groups for different tasks. Use reset_tools to activate the "
            "right group, then use skills within that group. "
            "Keep responses concise."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[Read(), Bash(), Glob(), Grep()],
            tool_groups=[
                ToolGroup(
                    name="visualization",
                    description=(
                        "Chart and visualization tools. Activate when "
                        "the user wants to create charts or plots."
                    ),
                    instructions=(
                        "Use the chart_generator skill to guide chart "
                        "creation. Always read the skill first."
                    ),
                    skills_or_loaders=[
                        LocalSkillLoader(
                            str(SKILLS_DIR / "chart_generator"),
                        ),
                    ],
                ),
                ToolGroup(
                    name="reporting",
                    description=(
                        "Report generation tools. Activate when the user "
                        "wants to create analysis reports."
                    ),
                    instructions=(
                        "Use the report_writer skill to guide report "
                        "creation. Follow the template structure."
                    ),
                    skills_or_loaders=[
                        LocalSkillLoader(
                            str(SKILLS_DIR / "report_writer"),
                        ),
                    ],
                ),
            ],
        ),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    print("  Tool groups: basic (always on), visualization, reporting")

    # Task 1: Should activate visualization group
    await stream_reply(
        agent,
        f"Create a pie chart showing the revenue distribution by category "
        f"from {SALES_CSV}. Save to /tmp/revenue_pie.png.",
    )

    # Task 2: Should activate reporting group
    await stream_reply(
        agent,
        f"Now write a brief analysis report about the sales data in "
        f"{SALES_CSV}. Save the report to /tmp/sales_report.md.",
    )


# =========================================================================
# Example 3: Skill anatomy walkthrough
# =========================================================================
async def example_skill_anatomy() -> None:
    """Walk through the structure of a skill."""
    print("\n" + "=" * 60)
    print("Example 3: Skill Anatomy")
    print("=" * 60)

    loader = LocalSkillLoader(
        directory=str(SKILLS_DIR),
        scan_subdir=True,
    )
    skills = await loader.list_skills()

    for skill in skills:
        print(f"\n  Skill: {skill.name}")
        print(f"  ├─ Description: {skill.description[:70]}...")
        print(f"  ├─ Directory: {skill.dir}")
        print(f"  ├─ Updated at: {skill.updated_at}")
        preview = skill.markdown[:200].replace("\n", "\n  │  ")
        print(f"  └─ Content preview:\n  │  {preview}...")

    print(
        """
  How it works:
  ─────────────
  1. SKILL.md frontmatter → name + description (shown in system prompt)
  2. SKILL.md body → full instructions (loaded on demand via Skill)
  3. Agent sees skill list → decides which skill to use
  4. Agent calls Skill(skill="chart_generator") → gets full instructions
  5. Agent follows instructions using Bash, Read, Write tools
""",
    )


# =========================================================================
# Main
# =========================================================================
async def main() -> None:
    print("Tutorial 06: Skills")
    print("=" * 60)

    if not SALES_CSV.exists():
        print(f"ERROR: {SALES_CSV} not found.")
        print("Run: cd tutorials/data && python generate_sales_data.py")
        return

    if not SKILLS_DIR.exists():
        print(f"ERROR: {SKILLS_DIR} not found.")
        return

    model = DashScopeChatModel(
        credential=DashScopeCredential(
            api_key=os.environ["DASHSCOPE_API_KEY"],
        ),
        model="qwen-plus",
    )

    # Example 1: Skills in basic group
    await example_basic_skills(model)

    # Example 2: Skills in ToolGroups
    await example_skills_in_groups(model)

    # Example 3: Skill anatomy (no model needed)
    await example_skill_anatomy()

    print("\n" + "=" * 60)
    print("Tutorial 06 complete! Next: Tutorial 07 — Permission System")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
