# -*- coding: utf-8 -*-
"""Tutorial 13: Agent Service — Deploy DataMuse as a shared service.

This tutorial demonstrates:
- Using create_app() to build a FastAPI service
- Zero-dep storage via fakeredis (swap to real Redis when deployed)
- InMemoryMessageBus for local event delivery
- extra_agent_tools for injecting server-side DataMuse tools
- LocalWorkspaceManager with skill_paths to inject T06 skills
- The complete API flow: Credential → Agent → Session → Stream + Chat
- SSE streaming from the Session stream endpoint

Two ways to drive the service:
  - terminal A: python main.py            (this file — starts the service)
  - terminal B: python client.py          (httpx walkthrough of the 5 steps)

Or use the companion Web UI in examples/web_ui.

Prerequisites:
- pip install "agentscope[service]" httpx
- pip install fakeredis            # zero-dep in-memory storage
- DASHSCOPE_API_KEY (or OPENAI_API_KEY) in env
"""
# pylint: disable=import-outside-toplevel
import csv
import os
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
)
from agentscope.tool import ToolBase, ToolChunk

TUTORIAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TUTORIAL_DIR.parent.parent
SALES_CSV = REPO_ROOT / "tutorials" / "data" / "sales_data.csv"


def _load_sales_rows() -> list[dict[str, str]]:
    """Load the shared tutorial dataset on the service host."""
    with SALES_CSV.open("r", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


class SalesProfile(ToolBase):
    """Return a compact profile of the shared sales dataset."""

    name = "SalesProfile"
    description = (
        "Inspect the sales dataset and return its row count, columns, date "
        "range, and three sample rows."
    )
    input_schema = {"type": "object", "properties": {}, "required": []}
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(
        self,
        _tool_input: dict[str, Any],
        _context: PermissionContext,
    ) -> PermissionDecision:
        """Allow this fixed, read-only server-side query."""
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="SalesProfile only reads the tutorial dataset.",
        )

    async def call(self) -> ToolChunk:
        """Profile the sales CSV."""
        rows = _load_sales_rows()
        columns = list(rows[0]) if rows else []
        dates = sorted(row["date"] for row in rows)
        lines = [
            "Sales data profile",
            f"- rows: {len(rows)}",
            f"- columns: {', '.join(columns)}",
            (
                f"- date range: {dates[0]} to {dates[-1]}"
                if dates
                else "- date range: n/a"
            ),
            "- sample rows:",
        ]
        lines.extend(f"  - {row}" for row in rows[:3])
        return ToolChunk(content=[TextBlock(text="\n".join(lines))])


class SalesBreakdown(ToolBase):
    """Aggregate sales by a supported business dimension."""

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
                "enum": [
                    "category",
                    "region",
                    "payment_method",
                    "customer_tier",
                ],
                "description": "Business dimension used for grouping.",
            },
        },
        "required": ["group_by"],
    }
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(
        self,
        _tool_input: dict[str, Any],
        _context: PermissionContext,
    ) -> PermissionDecision:
        """Allow this fixed, read-only server-side aggregation."""
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="SalesBreakdown only reads the tutorial dataset.",
        )

    async def call(self, group_by: str) -> ToolChunk:
        """Return a Markdown breakdown for the requested dimension."""
        rows = _load_sales_rows()
        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            groups.setdefault(row[group_by], []).append(row)

        lines = [
            f"Sales breakdown by {group_by}",
            "group | orders | revenue | avg_order",
            "--- | ---: | ---: | ---:",
        ]
        for key, group_rows in sorted(
            groups.items(),
            key=lambda item: sum(float(row["total"]) for row in item[1]),
            reverse=True,
        ):
            revenue = sum(float(row["total"]) for row in group_rows)
            average = revenue / len(group_rows)
            lines.append(
                f"{key} | {len(group_rows)} | ${revenue:,.2f} | "
                f"${average:,.2f}",
            )

        return ToolChunk(content=[TextBlock(text="\n".join(lines))])


async def datamuse_tools(
    _user_id: str,
    _agent_id: str,
    _session_id: str,
) -> list[ToolBase]:
    """Build fresh DataMuse tools for each service-side Agent assembly."""
    return [SalesProfile(), SalesBreakdown()]


def _make_inmemory_storage() -> Any:
    """Build a RedisStorage backed by an in-process fakeredis client.

    Same pattern AgentScope's own RedisStorage unit tests use — no Redis
    server required, no extra StorageBase implementation to maintain.
    """
    try:
        import fakeredis.aioredis
    except ImportError as missing:
        raise ImportError(
            "Tutorial 13 defaults to an in-memory store backed by fakeredis. "
            "Install it with: pip install fakeredis\n"
            "Or edit main.py to use RedisStorage(host=..., port=...).",
        ) from missing

    from agentscope.app.storage import RedisStorage

    # pylint: disable=protected-access
    # Mirrors the pattern in tests/storage_redis_test.py — we deliberately
    # construct a bare RedisStorage and swap its backing client for fakeredis.
    storage = RedisStorage.__new__(RedisStorage)
    storage._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    storage._external_pool = None
    storage._owned_pool = None
    storage.key_ttl = None
    storage.key_config = RedisStorage.KeyConfig()
    return storage


def create_service() -> tuple[Any, Any]:
    """Create the AgentScope service application."""
    import uvicorn
    from fastapi.middleware import Middleware
    from fastapi.middleware.cors import CORSMiddleware

    from agentscope.app import create_app
    from agentscope.app.message_bus import InMemoryMessageBus
    from agentscope.app.workspace_manager import LocalWorkspaceManager

    basedir = str(TUTORIAL_DIR / "workspaces")

    # Seed every new workspace with T06's report_writer skill so the Agent
    # can produce Markdown reports through a real Skill, not just by hand.
    skill_dirs = [
        str(
            REPO_ROOT / "tutorials" / "06_skills" / "skills" / "report_writer",
        ),
    ]

    app = create_app(
        storage=_make_inmemory_storage(),
        message_bus=InMemoryMessageBus(),
        workspace_manager=LocalWorkspaceManager(
            basedir=basedir,
            skill_paths=skill_dirs,
        ),
        extra_agent_tools=datamuse_tools,
        extra_middlewares=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ],
        title="DataMuse Service",
        version="1.0.0",
    )

    return app, uvicorn


def print_overview() -> None:
    """Print where to go next once the service is running."""
    print(
        """
Tutorial 13: Agent Service
============================================================
Storage : fakeredis (in-memory)        — swap RedisStorage for deployment
Bus     : InMemoryMessageBus           — swap RedisMessageBus for workers
Skills  : tutorials/06_skills/skills/report_writer injected
Tools   : SalesProfile + SalesBreakdown injected by extra_agent_tools
Docs    : http://localhost:8000/docs

Drive the service in another terminal:
  python client.py        — Python httpx walkthrough (5 API calls)

Or with curl:
  Step 1  POST /credential/         Register a Credential
  Step 2  POST /agent/              Create an Agent template
  Step 3  POST /sessions/           Create a Session + bind a model
  Step 4  GET  /sessions/{id}/stream?agent_id=...
  Step 5  POST /chat/               Trigger a reply
  Step 6  GET  /sessions/{id}/messages?agent_id=...

Or with the official Web UI:
  cd examples/web_ui && pnpm install && pnpm dev
  Setup page: server http://localhost:8000, username demo-user

Press Ctrl+C to stop.
""",
    )


if __name__ == "__main__":
    print_overview()

    if not os.getenv("DASHSCOPE_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        print(
            "WARNING: neither DASHSCOPE_API_KEY nor OPENAI_API_KEY is set. "
            "The service will start but /chat calls will fail until you "
            "register a working credential.\n",
        )

    try:
        service_app, runner = create_service()
    except ImportError as exc:
        print(f"\nCannot start service: {exc}")
        raise SystemExit(1) from exc

    runner.run(service_app, host="0.0.0.0", port=8000)
