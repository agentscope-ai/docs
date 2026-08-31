# -*- coding: utf-8 -*-
"""Tutorial 14: Scheduling — drive the /schedule API from Python.

Walks the full CRUD for the Schedule router that ships with
``agentscope.app.create_app``:

    POST   /credential/             — register a Credential (idempotent)
    POST   /agent/                  — register a DataMuse Agent (idempotent)
    POST   /schedule/               — create a Stateless schedule
    POST   /schedule/               — create a Stateful schedule
    GET    /schedule/               — list schedules
    GET    /schedule/{id}/sessions  — list sessions triggered by a schedule
    DELETE /schedule/{id}           — clean up

Prerequisites
-------------
* Terminal A:   ``cd tutorials/13_agent_service && python main.py``
                  (fakeredis-backed service on http://localhost:8000)
* Terminal B:   ``python main.py``      (this file)
* DASHSCOPE_API_KEY or OPENAI_API_KEY in env

Notes
-----
We use a 5-minute cron so a curious reader can wait a bit and watch a real
trigger. Change ``CRON_STATELESS`` to ``"*/1 * * * *"`` if you want it sooner.
"""
# pylint: disable=missing-function-docstring
import asyncio
import json
import os
import sys

import httpx


BASE_URL = os.getenv("AGENTSCOPE_SERVICE_URL", "http://localhost:8000")
USER_ID = os.getenv("AGENTSCOPE_USER_ID", "demo-user")
HEADERS = {"X-User-Id": USER_ID, "Content-Type": "application/json"}

CRON_STATELESS = "*/5 * * * *"  # every 5 minutes
CRON_STATEFUL = "*/10 * * * *"  # every 10 minutes


def _pick_credential_payload() -> tuple[dict, str, str]:
    """Pick whichever provider has its API key in the environment."""
    if os.getenv("DASHSCOPE_API_KEY"):
        return (
            {
                "data": {
                    "type": "dashscope_credential",
                    "api_key": os.environ["DASHSCOPE_API_KEY"],
                },
            },
            "dashscope_chat",
            "qwen-plus",
        )
    if os.getenv("OPENAI_API_KEY"):
        return (
            {
                "data": {
                    "type": "openai_credential",
                    "api_key": os.environ["OPENAI_API_KEY"],
                },
            },
            "openai_chat",
            "gpt-4o",
        )
    print(
        "ERROR: set DASHSCOPE_API_KEY or OPENAI_API_KEY first.",
        file=sys.stderr,
    )
    raise SystemExit(1)


async def _ensure_credential(
    client: httpx.AsyncClient,
) -> tuple[str, str, str]:
    cred_body, model_type, model_name = _pick_credential_payload()
    resp = await client.post("/credential/", json=cred_body, headers=HEADERS)
    resp.raise_for_status()
    credential_id = resp.json()["credential_id"]
    print(f"  credential_id = {credential_id}")
    return credential_id, model_type, model_name


async def _ensure_agent(client: httpx.AsyncClient) -> str:
    body = {
        "name": "DataMuse",
        "system_prompt": (
            "You are DataMuse, a sales-data analyst running unattended on a "
            "schedule. Use SalesProfile and SalesBreakdown to inspect the "
            "server-side dataset, then summarize the headline numbers in "
            "5 bullet points. Do not guess figures or request file paths."
        ),
    }
    resp = await client.post("/agent/", json=body, headers=HEADERS)
    resp.raise_for_status()
    agent_id = resp.json()["agent_id"]
    print(f"  agent_id      = {agent_id}")
    return agent_id


async def create_stateless_schedule(
    client: httpx.AsyncClient,
    agent_id: str,
    credential_id: str,
    model_type: str,
    model_name: str,
) -> str:
    body = {
        "name": "Daily Sales Summary",
        "description": (
            "Use SalesProfile, then SalesBreakdown by category, and produce "
            "a 5-bullet headline sales summary."
        ),
        "cron_expression": CRON_STATELESS,
        "timezone": "Asia/Shanghai",
        "agent_id": agent_id,
        "chat_model_config": {
            "type": model_type,
            "credential_id": credential_id,
            "model": model_name,
            "parameters": {},
        },
        "stateful": False,
        "permission_mode": "dont_ask",
    }
    resp = await client.post("/schedule/", json=body, headers=HEADERS)
    resp.raise_for_status()
    schedule_id = resp.json()["schedule_id"]
    print(f"  [stateless] schedule_id = {schedule_id}  ({CRON_STATELESS})")
    return schedule_id


async def create_stateful_schedule(
    client: httpx.AsyncClient,
    agent_id: str,
    credential_id: str,
    model_type: str,
    model_name: str,
) -> str:
    body = {
        "name": "Sales Trend Tracker",
        "description": (
            "Use SalesProfile and SalesBreakdown by region. Re-run the same "
            "session so DataMuse can compare with its previous summary and "
            "call out changes."
        ),
        "cron_expression": CRON_STATEFUL,
        "timezone": "Asia/Shanghai",
        "agent_id": agent_id,
        "chat_model_config": {
            "type": model_type,
            "credential_id": credential_id,
            "model": model_name,
            "parameters": {},
        },
        "stateful": True,
        "permission_mode": "dont_ask",
    }
    resp = await client.post("/schedule/", json=body, headers=HEADERS)
    resp.raise_for_status()
    schedule_id = resp.json()["schedule_id"]
    print(f"  [stateful]  schedule_id = {schedule_id}  ({CRON_STATEFUL})")
    return schedule_id


async def list_schedules(client: httpx.AsyncClient) -> None:
    resp = await client.get("/schedule/", headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    print(f"  total = {data['total']}")
    for record in data["schedules"]:
        d = record["data"]
        print(
            f"    - {record['id'][:8]}  "
            f"{d['name']!r}  cron={d['cron_expression']}  "
            f"stateful={d['stateful']}  enabled={d['enabled']}",
        )


async def list_sessions_for_schedule(
    client: httpx.AsyncClient,
    schedule_id: str,
) -> None:
    resp = await client.get(
        f"/schedule/{schedule_id}/sessions",
        headers=HEADERS,
    )
    resp.raise_for_status()
    data = resp.json()
    print(
        f"  schedule {schedule_id[:8]}  triggered_sessions = {data['total']}",
    )
    if data["total"] == 0:
        print(
            "    (none yet — wait for the next cron tick, "
            "or shorten the cron expression at the top of this file)",
        )


async def delete_schedule(client: httpx.AsyncClient, schedule_id: str) -> None:
    resp = await client.delete(f"/schedule/{schedule_id}", headers=HEADERS)
    if resp.status_code not in (200, 204):
        print(f"  WARN: delete returned {resp.status_code}: {resp.text}")
        return
    print(f"  deleted {schedule_id[:8]}")


async def main() -> None:
    print(f"Talking to {BASE_URL} as user {USER_ID!r}")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        print("\n[1/5] ensure credential + agent")
        cred_id, model_type, model_name = await _ensure_credential(client)
        agent_id = await _ensure_agent(client)

        print("\n[2/5] create a stateless schedule")
        stateless_id = await create_stateless_schedule(
            client,
            agent_id,
            cred_id,
            model_type,
            model_name,
        )

        print("\n[3/5] create a stateful schedule")
        stateful_id = await create_stateful_schedule(
            client,
            agent_id,
            cred_id,
            model_type,
            model_name,
        )

        print("\n[4/5] list every schedule we own")
        await list_schedules(client)

        print("\n[5/5] peek at triggered sessions for each schedule")
        await list_sessions_for_schedule(client, stateless_id)
        await list_sessions_for_schedule(client, stateful_id)

        cleanup = os.getenv("CLEANUP", "1") != "0"
        if cleanup:
            print(
                "\n[cleanup] delete the two schedules (set CLEANUP=0 to keep)",
            )
            await delete_schedule(client, stateless_id)
            await delete_schedule(client, stateful_id)
        else:
            print(
                "\n[cleanup] skipped (CLEANUP=0). "
                "Leave the schedules running and re-run "
                "list_sessions_for_schedule after a few minutes to see "
                "real trigger output.",
            )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except httpx.ConnectError as exc:
        print(
            f"\nERROR: cannot reach {BASE_URL}. Start the service first:\n"
            "  cd ../13_agent_service && python main.py",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except httpx.HTTPStatusError as exc:
        print(
            f"\nERROR: {exc.request.method} {exc.request.url} "
            f"returned {exc.response.status_code}",
            file=sys.stderr,
        )
        try:
            print(json.dumps(exc.response.json(), indent=2), file=sys.stderr)
        except Exception:
            print(exc.response.text, file=sys.stderr)
        raise SystemExit(1) from exc
