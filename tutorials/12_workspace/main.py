# -*- coding: utf-8 -*-
"""Tutorial 12: Workspace — Agent's unified working environment.

This tutorial demonstrates:
- LocalWorkspace: initialization, directory layout, lifecycle
- Built-in tools provided by workspace (Bash, Read, Write, etc.)
- Workspace as Offloader: context and tool result persistence
- Dynamic skill management: add_skill / remove_skill
- Using workspace with an Agent for a complete analysis task
"""
# pylint: disable=missing-function-docstring
import asyncio
import os
from pathlib import Path

from agentscope.agent import Agent, ContextConfig
from agentscope.credential import DashScopeCredential
from agentscope.event import EventType
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.state import AgentState
from agentscope.tool import Toolkit
from agentscope.workspace import LocalWorkspace

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SALES_CSV = DATA_DIR / "sales_data.csv"
WORKSPACE_DIR = Path(__file__).resolve().parent / "workspace"


# =========================================================================
# Example 1: Workspace basics
# =========================================================================
async def example_workspace_basics() -> None:
    """Demonstrate workspace initialization and inspection."""
    print("\n" + "=" * 60)
    print("Example 1: Workspace Basics")
    print("=" * 60)

    workspace = LocalWorkspace(workdir=str(WORKSPACE_DIR))
    await workspace.initialize()

    try:
        print(f"\n  workspace_id: {workspace.workspace_id}")
        print(f"  workdir:      {workspace.workdir}")
        print(f"  is_alive:     {workspace.is_alive}")

        # List built-in tools
        tools = await workspace.list_tools()
        print(f"\n  Built-in tools ({len(tools)}):")
        for tool in tools:
            print(f"    - {tool.name}: {tool.description[:60]}...")

        # List MCPs and skills
        mcps = await workspace.list_mcps()
        skills = await workspace.list_skills()
        print(f"\n  MCPs: {len(mcps)}")
        print(f"  Skills: {len(skills)}")

        # Get workspace instructions
        instructions = await workspace.get_instructions()
        preview = instructions[:200].replace("\n", "\n    ")
        print(f"\n  Instructions (preview):\n    {preview}...")

        # Directory layout
        print("\n  Directory layout:")
        for item in sorted(Path(workspace.workdir).rglob("*")):
            rel = item.relative_to(workspace.workdir)
            prefix = "    " + "  " * (len(rel.parts) - 1)
            print(f"{prefix}{'/' if item.is_dir() else ''}{rel.name}")

    finally:
        await workspace.close()

    print("\n  Workspace closed.")


# =========================================================================
# Example 2: Skill management
# =========================================================================
async def example_skill_management() -> None:
    """Demonstrate dynamic skill add/remove."""
    print("\n" + "=" * 60)
    print("Example 2: Dynamic Skill Management")
    print("=" * 60)

    # Check if we have skills from Tutorial 06
    skills_dir = (
        Path(__file__).resolve().parent.parent / "06_skills" / "skills"
    )

    workspace = LocalWorkspace(workdir=str(WORKSPACE_DIR))
    await workspace.initialize()

    try:
        # Show initial state
        skills = await workspace.list_skills()
        print(f"\n  Initial skills: {len(skills)}")

        if skills_dir.exists():
            # Add skills from Tutorial 06
            chart_skill = skills_dir / "chart_generator"
            if chart_skill.exists():
                print(f"\n  Adding skill from: {chart_skill}")
                await workspace.add_skill(str(chart_skill))

                skills = await workspace.list_skills()
                print(f"  Skills after add: {len(skills)}")
                for skill in skills:
                    print(f"    - {skill.name}: {skill.description[:60]}...")

                # Remove the skill
                print(f"\n  Removing skill: {skills[0].name}")
                await workspace.remove_skill(skills[0].name)

                skills = await workspace.list_skills()
                print(f"  Skills after remove: {len(skills)}")
        else:
            print(
                "\n  (Tutorial 06 skills not found — showing API pattern "
                "only)",
            )
            print(
                """
  # Dynamic skill management API:
  await workspace.add_skill("/path/to/skill_dir")   # add
  skills = await workspace.list_skills()             # list
  await workspace.remove_skill("skill-name")         # remove
""",
            )

    finally:
        await workspace.close()


# =========================================================================
# Example 3: Workspace as Offloader
# =========================================================================
async def example_offloader() -> None:
    """Demonstrate workspace offloading with an Agent."""
    print("\n" + "=" * 60)
    print("Example 3: Workspace as Offloader")
    print("=" * 60)

    model = DashScopeChatModel(
        credential=DashScopeCredential(
            api_key=os.environ["DASHSCOPE_API_KEY"],
        ),
        model="qwen-plus",
    )
    workspace = LocalWorkspace(workdir=str(WORKSPACE_DIR))
    await workspace.initialize()

    try:
        agent = Agent(
            name="DataMuse",
            system_prompt=(
                "You are DataMuse, a data analyst. Use Read to inspect "
                f"the sales data at {SALES_CSV}. Be concise."
            ),
            model=model,
            toolkit=Toolkit(
                tools=await workspace.list_tools(),
                skills_or_loaders=await workspace.list_skills(),
                mcps=await workspace.list_mcps(),
            ),
            context_config=ContextConfig(
                tool_result_limit=800,
            ),
            state=AgentState(
                permission_context=PermissionContext(
                    mode=PermissionMode.BYPASS,
                ),
            ),
            offloader=workspace,
        )

        # Send a task that produces a large tool result
        msg = UserMsg(
            name="user",
            content=(
                f"Read the first 20 lines of {SALES_CSV} and tell me "
                "the column names and data types."
            ),
        )

        print("\n  Sending task to Agent with workspace offloader...")
        text_parts = []
        async for event in agent.reply_stream(msg):
            match event.type:
                case EventType.TEXT_BLOCK_DELTA:
                    text_parts.append(event.delta)
                case EventType.TOOL_CALL_START:
                    print(
                        f"    >> Tool: {event.tool_call_name}",
                        end="",
                        flush=True,
                    )
                case EventType.TOOL_RESULT_END:
                    print(f" [{event.state}]")

        text = "".join(text_parts)
        print(f"\n  Agent response: {text[:200]}...")

        # Check what was offloaded
        sessions_dir = Path(workspace.workdir) / "sessions"
        if sessions_dir.exists():
            print(f"\n  Offloaded files in {sessions_dir}:")
            for item in sorted(sessions_dir.rglob("*")):
                if item.is_file():
                    rel = item.relative_to(sessions_dir)
                    size = item.stat().st_size
                    print(f"    {rel} ({size} bytes)")
        else:
            print("\n  (No offloaded files yet — tool results were small)")

    finally:
        await workspace.close()


# =========================================================================
# Example 4: Architecture overview
# =========================================================================
async def example_architecture() -> None:
    """Display workspace architecture patterns."""
    print("\n" + "=" * 60)
    print("Example 4: Workspace Architecture")
    print("=" * 60)

    print(
        """
  WorkspaceBase Protocol
  ──────────────────────

  ┌─────────────────────────────────────────────────────────┐
  │  WorkspaceBase                                           │
  │                                                          │
  │  Lifecycle:                                              │
  │    initialize()  →  close()  →  reset()                  │
  │                                                          │
  │  Resource Discovery (consumed by Agent):                 │
  │    list_tools()    → [Bash, Read, Write, Edit, ...]      │
  │    list_mcps()     → [MCPClient, ...]                    │
  │    list_skills()   → [Skill, ...]                        │
  │    get_instructions() → system prompt fragment           │
  │                                                          │
  │  Offload (consumed by Agent):                            │
  │    offload_context(session_id, msgs)                     │
  │    offload_tool_result(session_id, tool_result)          │
  │                                                          │
  │  Dynamic Management (consumed by User/UI):               │
  │    add_mcp(client) / remove_mcp(name)                    │
  │    add_skill(path) / remove_skill(name)                  │
  └─────────────────────────────────────────────────────────┘

  Workspace Implementations
  ─────────────────────────

  LocalWorkspace       DockerWorkspace      E2BWorkspace        K8sWorkspace
  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐    ┌──────────┐
  │ ./workspace │      │ Docker      │      │ E2B Cloud   │    │ Pod/PVC  │
  │ local files │      │ container   │      │ sandbox     │    │ cluster  │
  └─────────────┘      └─────────────┘      └─────────────┘    └──────────┘
  本地目录              容器隔离              云端隔离            K8s 隔离

  Workspace in Agent Construction
  ────────────────────────────────

  workspace = LocalWorkspace(workdir="./ws")
  await workspace.initialize()

  agent = Agent(
      toolkit=Toolkit(
          tools=await workspace.list_tools(),
          skills_or_loaders=await workspace.list_skills(),
          mcps=await workspace.list_mcps(),
      ),
      offloader=workspace,   # ← same object serves as Offloader
  )

  # At shutdown
  await workspace.close()

  Workspace in Agent Service (Tutorial 13)
  ──────────────────────────────────────────

  # WorkspaceManager creates per-session workspaces
  from agentscope.app import create_app
  from agentscope.app.message_bus import InMemoryMessageBus
  from agentscope.app.storage import RedisStorage
  from agentscope.app.workspace_manager import LocalWorkspaceManager

  manager = LocalWorkspaceManager(
      basedir="./workspaces",
      default_mcps=[...],
      skill_paths=["./skills/analyst"],
  )

  app = create_app(
      storage=RedisStorage(...),
      message_bus=InMemoryMessageBus(),
      workspace_manager=manager,
  )
""",
    )


# =========================================================================
# Main
# =========================================================================
async def main() -> None:
    print("Tutorial 12: Workspace")
    print("=" * 60)

    if not SALES_CSV.exists():
        print(f"ERROR: {SALES_CSV} not found.")
        print("Run: cd tutorials/data && python generate_sales_data.py")
        return

    # Example 1: Basics
    await example_workspace_basics()

    # Example 2: Skill management
    await example_skill_management()

    # Example 3: Offloader
    await example_offloader()

    # Example 4: Architecture
    await example_architecture()

    print("\n" + "=" * 60)
    print("Tutorial 12 complete! Next: Tutorial 13 — Agent Service")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
