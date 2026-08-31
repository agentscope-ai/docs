# -*- coding: utf-8 -*-
"""Tutorial 05: MCP Integration — Connect external tool servers.

This tutorial demonstrates:
- Connecting to MCP servers using StdioMCPConfig and HttpMCPConfig
- Stateful vs Stateless MCP connections
- MCP tool namespacing (mcp__{server}__{tool})
- Tool filtering with enable_tools / disable_tools
- Mixing MCP tools with local tools
"""
# pylint: disable=missing-function-docstring
import asyncio
import os
import shutil
from pathlib import Path

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.event import EventType
from agentscope.mcp import MCPClient, StdioMCPConfig, HttpMCPConfig
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.state import AgentState
from agentscope.tool import Toolkit, Read, Glob, Grep

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SALES_CSV = DATA_DIR / "sales_data.csv"


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
# Example 1: Stdio MCP — local filesystem server
# =========================================================================
async def example_stdio_mcp(model) -> None:
    """Connect to a local filesystem MCP server via stdio."""
    print("\n" + "=" * 60)
    print("Example 1: Stdio MCP (Filesystem Server)")
    print("=" * 60)

    # Check if npx is available
    if not shutil.which("npx"):
        print("  [SKIP] npx not found. Install Node.js to try Stdio MCP.")
        print("  Showing configuration example instead:\n")
        print("  client = MCPClient(")
        print('      name="filesystem",')
        print("      is_stateful=True,")
        print("      mcp_config=StdioMCPConfig(")
        print('          command="npx",')
        print(
            '          args=["-y", "@modelcontextprotocol/server-filesystem",',
        )
        print(f'                "{DATA_DIR}"],')
        print("      ),")
        print('      enable_tools=["read_file", "list_directory"],')
        print("  )")
        return

    # Create a Stdio MCP client for the filesystem server
    fs_client = MCPClient(
        name="filesystem",
        is_stateful=True,
        mcp_config=StdioMCPConfig(
            command="npx",
            args=[
                "-y",
                "@modelcontextprotocol/server-filesystem",
                str(DATA_DIR),
            ],
        ),
        enable_tools=["read_file", "list_directory"],
    )

    # Stateful client: must connect before use
    print("  Connecting to filesystem MCP server...")
    await fs_client.connect()
    print("  Connected!")

    # List available tools
    tools = await fs_client.list_tools()
    print(f"  Available tools ({len(tools)}):")
    for tool in tools:
        print(f"    - {tool.name}: {tool.description[:60]}...")

    # Create agent with MCP tools + local tools
    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a data analysis assistant. You have access to "
            "filesystem tools via MCP and local tools for text search. "
            "Keep responses concise."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[Grep()],
            mcps=[fs_client],
        ),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    # Use the agent with MCP tools
    await stream_reply(
        agent,
        f"List the files in {DATA_DIR} using the filesystem MCP tools, "
        "then read the first 5 lines of sales_data.csv.",
    )

    # Clean up
    await fs_client.close()
    print("  MCP connection closed.")


# =========================================================================
# Example 2: MCP configuration patterns
# =========================================================================
async def example_mcp_config() -> None:
    """Demonstrate different MCP configuration patterns."""
    print("\n" + "=" * 60)
    print("Example 2: MCP Configuration Patterns")
    print("=" * 60)

    # --- Pattern 1: Stdio MCP (stateful, local process) ---
    print("\n  Pattern 1: Stdio MCP (stateful)")
    print("  ─────────────────────────────────")
    stdio_client = MCPClient(
        name="sqlite",
        is_stateful=True,
        mcp_config=StdioMCPConfig(
            command="npx",
            args=[
                "-y",
                "@modelcontextprotocol/server-sqlite",
                "/tmp/demo.db",
            ],
            env={"NODE_ENV": "production"},
        ),
    )
    print(f"  Name: {stdio_client.name}")
    print(f"  Stateful: {stdio_client.is_stateful}")
    print(f"  Config type: {stdio_client.mcp_config.type}")
    print(f"  Command: {stdio_client.mcp_config.command}")

    # --- Pattern 2: HTTP MCP (stateless, remote service) ---
    print("\n  Pattern 2: HTTP MCP (stateless)")
    print("  ────────────────────────────────")
    http_client = MCPClient(
        name="weather",
        is_stateful=False,
        mcp_config=HttpMCPConfig(
            url="https://api.example.com/mcp",
            headers={"Authorization": "Bearer demo-token"},
            timeout=30.0,
        ),
    )
    print(f"  Name: {http_client.name}")
    print(f"  Stateful: {http_client.is_stateful}")
    print(f"  Config type: {http_client.mcp_config.type}")
    print(f"  URL: {http_client.mcp_config.url}")

    # --- Pattern 3: HTTP MCP (stateful, persistent session) ---
    print("\n  Pattern 3: HTTP MCP (stateful)")
    print("  ───────────────────────────────")
    stateful_http = MCPClient(
        name="database",
        is_stateful=True,
        mcp_config=HttpMCPConfig(
            url="http://localhost:8080/mcp",
            timeout=60.0,
        ),
    )
    print(f"  Name: {stateful_http.name}")
    print(f"  Stateful: {stateful_http.is_stateful}")
    print(f"  Config type: {stateful_http.mcp_config.type}")

    # --- Pattern 4: Tool filtering ---
    print("\n  Pattern 4: Tool Filtering")
    print("  ──────────────────────────")
    filtered_client = MCPClient(
        name="fs_readonly",
        is_stateful=True,
        mcp_config=StdioMCPConfig(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        ),
        disable_tools=["write_file", "create_directory", "move_file"],
    )
    print(f"  Name: {filtered_client.name}")
    print(f"  Disabled tools: {filtered_client.disable_tools}")
    print("  → Only read-only operations will be exposed to the Agent")


# =========================================================================
# Example 3: MCP + local tools in ToolGroups
# =========================================================================
async def example_mcp_with_tool_groups() -> None:
    """Show how MCP tools integrate with ToolGroups."""
    print("\n" + "=" * 60)
    print("Example 3: MCP + ToolGroups Architecture")
    print("=" * 60)

    print(
        """
  MCP tools seamlessly integrate with ToolGroups:

  toolkit = Toolkit(
      # Basic group (always active): local tools + MCP
      tools=[Read(), Glob(), Grep()],
      mcps=[filesystem_mcp],

      tool_groups=[
          # Named group: MCP tools activated on demand
          ToolGroup(
              name="database",
              description="Database query tools",
              mcps=[database_mcp],
              tools=[SalesSummary()],
          ),
          ToolGroup(
              name="web",
              description="Web browsing tools",
              mcps=[browser_mcp],
          ),
      ],
  )

  Key behaviors:
  ─────────────
  • MCP tools in 'basic' group → always available
  • MCP tools in named groups → activated via reset_tools
  • Tool names follow mcp__{server}__{tool} pattern
  • enable_tools/disable_tools filter at MCPClient level
  • ToolGroup activation/deactivation affects MCP tools too
""",
    )


# =========================================================================
# Example 4: Naming convention demo
# =========================================================================
async def example_naming_convention() -> None:
    """Demonstrate MCP tool naming conventions."""
    print("\n" + "=" * 60)
    print("Example 4: MCP Tool Naming Convention")
    print("=" * 60)

    print(
        """
  MCP tools are namespaced to prevent conflicts:

  Pattern: mcp__{server_name}__{tool_name}

  Examples:
  ────────
  Server: "filesystem"
    • read_file    → mcp__filesystem__read_file
    • write_file   → mcp__filesystem__write_file
    • list_dir     → mcp__filesystem__list_dir

  Server: "sqlite"
    • query        → mcp__sqlite__query
    • read_file    → mcp__sqlite__read_file   (no conflict!)

  Server: "browser"
    • navigate     → mcp__browser__navigate
    • screenshot   → mcp__browser__screenshot

  This namespacing ensures that even if two MCP servers
  expose tools with the same name, they remain distinct
  in the Agent's tool set.
""",
    )


# =========================================================================
# Example 5: Working demo with local tools
# =========================================================================
async def example_local_tools_demo(model) -> None:
    """Demo with local tools showing the same pattern MCP would follow."""
    print("\n" + "=" * 60)
    print("Example 5: Mixed Tools Demo (Local + MCP-ready)")
    print("=" * 60)

    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a data analysis assistant. Use the available "
            "tools to help the user explore and understand data files. "
            "Keep responses concise."
        ),
        model=model,
        toolkit=Toolkit(
            tools=[Read(), Glob(), Grep()],
        ),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
    )

    await stream_reply(
        agent,
        f"Find all CSV files under {DATA_DIR.parent} using Glob, then "
        "read the first 3 lines of the sales data CSV to preview its "
        "structure.",
    )


# =========================================================================
# Main
# =========================================================================
async def main() -> None:
    print("Tutorial 05: MCP Integration")
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

    # Example 1: Stdio MCP (requires Node.js)
    await example_stdio_mcp(model)

    # Example 2: Configuration patterns (no server needed)
    await example_mcp_config()

    # Example 3: MCP + ToolGroups architecture
    await example_mcp_with_tool_groups()

    # Example 4: Naming conventions
    await example_naming_convention()

    # Example 5: Working demo with local tools
    await example_local_tools_demo(model)

    print("\n" + "=" * 60)
    print("Tutorial 05 complete! Next: Tutorial 06 — Skills")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
