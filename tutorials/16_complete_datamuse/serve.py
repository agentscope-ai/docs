# -*- coding: utf-8 -*-
"""Tutorial 16: Complete DataMuse — lightweight Web UI mode.

Minimal FastAPI server that wraps the DataMuse agent and streams events via
SSE. Pairs with the included index.html for a browser-based experience.
Tools and middleware are imported from tools.py so this server stays in lock
step with main.py.

No Redis, no Node.js — just:
    pip install agentscope uvicorn fastapi
    python serve.py

Then open http://localhost:8000 in a browser.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=wrong-import-order
import asyncio
import json
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from agentscope.agent import Agent, ContextConfig
from agentscope.event import (
    ConfirmResult,
    EventType,
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
    ReportWriter,
    SALES_CSV,
    SalesBreakdown,
    SalesProfile,
    TimingMiddleware,
    WORKSPACE_DIR,
    create_model,
)

TUTORIAL_DIR = Path(__file__).resolve().parent


# =========================================================================
# Agent singleton
# =========================================================================
agent: Agent | None = None
workspace: LocalWorkspace | None = None
_pending_confirm: asyncio.Event | None = None
_confirm_result: UserConfirmResultEvent | None = None


async def get_agent() -> Agent:
    global agent, workspace
    if agent is not None:
        return agent

    model = create_model()
    workspace = LocalWorkspace(workdir=str(WORKSPACE_DIR))
    await workspace.initialize()

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
            tools=[SalesProfile(), SalesBreakdown(), ReportWriter()],
        ),
        context_config=ContextConfig(tool_result_limit=1200),
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.DEFAULT,
            ),
        ),
        middlewares=[TimingMiddleware()],
        offloader=workspace,
    )
    return agent


# =========================================================================
# FastAPI app
# =========================================================================
app = FastAPI(title="DataMuse Demo")


@app.get("/")
async def index():
    return FileResponse(TUTORIAL_DIR / "index.html")


class ChatRequest(BaseModel):
    message: str


class ConfirmRequest(BaseModel):
    reply_id: str
    tool_calls: list[dict[str, Any]]
    confirmed: bool


@app.post("/chat")
async def chat(req: ChatRequest):
    """Stream agent events as SSE."""
    ag = await get_agent()

    async def event_stream():
        global _pending_confirm, _confirm_result

        msg = UserMsg(name="user", content=req.message)
        async for event in ag.reply_stream(msg):
            payload = event.model_dump(mode="json")
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            if event.type == EventType.REQUIRE_USER_CONFIRM:
                _pending_confirm = asyncio.Event()
                _confirm_result = None
                yield f"data: {json.dumps({'type': 'WAITING_CONFIRM'})}\n\n"
                await _pending_confirm.wait()
                _pending_confirm = None

                async for cont_event in ag.reply_stream(_confirm_result):
                    cont_payload = cont_event.model_dump(mode="json")
                    yield (
                        f"data: {json.dumps(cont_payload, ensure_ascii=False)}"
                        "\n\n"
                    )

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/confirm")
async def confirm(req: ConfirmRequest):
    """Receive user confirmation for pending tool calls."""
    global _confirm_result

    from agentscope.message import ToolCallBlock

    confirm_results = []
    for tc_data in req.tool_calls:
        tc = ToolCallBlock(**tc_data)
        confirm_results.append(
            ConfirmResult(
                confirmed=req.confirmed,
                tool_call=tc,
                rules=None,
            ),
        )

    _confirm_result = UserConfirmResultEvent(
        reply_id=req.reply_id,
        confirm_results=confirm_results,
    )

    if _pending_confirm:
        _pending_confirm.set()

    return {"status": "ok"}


if __name__ == "__main__":
    if not SALES_CSV.exists():
        print(f"ERROR: {SALES_CSV} not found.")
        print("Run: cd tutorials/data && python generate_sales_data.py")
        raise SystemExit(1)

    print("DataMuse Web Demo")
    print("=" * 50)
    print("Open http://localhost:8000 in your browser")
    print(f"Dataset: {SALES_CSV}")
    print(f"Workspace: {WORKSPACE_DIR}")
    print("=" * 50)

    uvicorn.run(
        "serve:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
