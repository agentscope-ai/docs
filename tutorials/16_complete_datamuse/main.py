# -*- coding: utf-8 -*-
"""Tutorial 16: Complete DataMuse — end-to-end CLI demo.

Combines pieces from earlier chapters: Agent + model, custom tools (defined
once in tools.py and shared with serve.py), streaming events, permission
confirmation, ContextConfig, middleware, and a LocalWorkspace.
"""
# pylint: disable=missing-function-docstring,wrong-import-order
import asyncio
from typing import AsyncGenerator

from agentscope.agent import Agent, ContextConfig
from agentscope.event import (
    ConfirmResult,
    EventType,
    RequireUserConfirmEvent,
    UserConfirmResultEvent,
)
from agentscope.message import UserMsg
from agentscope.permission import (
    PermissionContext,
    PermissionMode,
)
from agentscope.state import AgentState
from agentscope.tool import Toolkit
from agentscope.workspace import LocalWorkspace

from tools import (
    ConsoleTraceMiddleware,
    ReportWriter,
    REPORTS_DIR,
    SALES_CSV,
    SalesBreakdown,
    SalesProfile,
    WORKSPACE_DIR,
    create_model,
)


async def _process_stream(
    agent: Agent,
    stream: AsyncGenerator,
    *,
    auto_confirm: bool = True,
) -> None:
    async for event in stream:
        match event.type:
            case EventType.TEXT_BLOCK_DELTA:
                print(event.delta, end="", flush=True)
            case EventType.TOOL_CALL_START:
                print(f"\n  >> Calling: {event.tool_call_name}")
            case EventType.TOOL_RESULT_END:
                print(f"  >> Tool finished: {event.state}")
            case EventType.REQUIRE_USER_CONFIRM:
                await _handle_confirmation(
                    agent,
                    event,
                    auto_confirm=auto_confirm,
                )
            case EventType.REPLY_END:
                print()


async def _handle_confirmation(
    agent: Agent,
    event: RequireUserConfirmEvent,
    *,
    auto_confirm: bool,
) -> None:
    print("\n  >> Confirmation required")
    confirm_results = []
    for tool_call in event.tool_calls:
        print(f"     tool: {tool_call.name}")
        print(f"     input: {tool_call.input[:160]}")
        if not auto_confirm:
            answer = input("Allow this tool call? [y/N] ").strip().lower()
            confirmed = answer in {"y", "yes"}
        else:
            print("     auto-confirmed for this tutorial demo")
            confirmed = True

        confirm_results.append(
            ConfirmResult(
                confirmed=confirmed,
                tool_call=tool_call,
                rules=(tool_call.suggested_rules or None)
                if confirmed
                else None,
            ),
        )

    confirm_event = UserConfirmResultEvent(
        reply_id=event.reply_id,
        confirm_results=confirm_results,
    )
    await _process_stream(
        agent,
        agent.reply_stream(confirm_event),
        auto_confirm=auto_confirm,
    )


async def main() -> None:
    if not SALES_CSV.exists():
        print(f"ERROR: {SALES_CSV} not found.")
        print("Run: cd tutorials/data && python generate_sales_data.py")
        return

    model = create_model()
    workspace = LocalWorkspace(workdir=str(WORKSPACE_DIR))
    await workspace.initialize()

    try:
        agent = Agent(
            name="DataMuse",
            system_prompt=(
                "You are DataMuse, a careful data analyst. Always inspect "
                "the dataset before making claims. Use SalesProfile first, "
                "then SalesBreakdown for relevant dimensions, then write a "
                "concise Markdown report with ReportWriter. Mention the "
                "report path in your final answer."
            ),
            model=model,
            toolkit=Toolkit(
                tools=[
                    SalesProfile(),
                    SalesBreakdown(),
                    ReportWriter(),
                ],
            ),
            context_config=ContextConfig(
                tool_result_limit=1200,
            ),
            state=AgentState(
                permission_context=PermissionContext(
                    mode=PermissionMode.DEFAULT,
                ),
            ),
            middlewares=[ConsoleTraceMiddleware()],
            offloader=workspace,
        )

        task = (
            "Analyze the sales dataset end to end. First inspect the data, "
            "then compare revenue by category, region, payment_method, and "
            "customer_tier. Identify the strongest business signals and write "
            "a short Markdown report named datamuse_sales_report.md."
        )

        print("Tutorial 16: Complete DataMuse")
        print("=" * 60)
        print(f"Dataset: {SALES_CSV}")
        print(f"Workspace: {WORKSPACE_DIR}")
        print("\n[User]: " + task)
        print("\n[DataMuse]: ", end="", flush=True)

        await _process_stream(
            agent,
            agent.reply_stream(UserMsg(name="user", content=task)),
            auto_confirm=True,
        )

        print("\nDone. Check the workspace reports directory:")
        print(f"  {REPORTS_DIR}")

    finally:
        await workspace.close()


if __name__ == "__main__":
    asyncio.run(main())
