# -*- coding: utf-8 -*-
"""Tutorial 13: Python client walkthrough of the Agent Service.

Runs against the FastAPI service started by `python main.py` in another
terminal. Walks the canonical 5-step flow:

    POST /credential/   →  POST /agent/   →  POST /sessions/
        →  GET /sessions/{id}/stream + POST /chat/
        →  GET  /sessions/{id}/messages

Prerequisites:
    pip install httpx
    python main.py        # in another terminal, on http://localhost:8000

Notes
-----
The service-side Agent template only stores ``name`` + ``system_prompt`` +
optional ``context_config`` / ``react_config``. **Custom Python tools cannot
be attached through the Agent-create HTTP payload**. They can be provided by
the service host through ``extra_agent_tools`` or by the workspace
(``default_mcps`` / ``skill_paths``). In this tutorial the DataMuse persona
survives the HTTP boundary, ``SalesProfile`` / ``SalesBreakdown`` come from
``extra_agent_tools``, and the report_writer skill comes from
``LocalWorkspaceManager(skill_paths=...)`` in ``main.py``.
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


def _pick_credential_payload() -> tuple[dict, str, str]:
    """Detect which provider key is available and return a matching payload.

    Returns: (credential_payload, model_type, model_name)
    """
    dashscope_key = os.getenv("DASHSCOPE_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if dashscope_key:
        return (
            {
                "data": {
                    "type": "dashscope_credential",
                    "api_key": dashscope_key,
                },
            },
            "dashscope_chat",
            "qwen-plus",
        )
    if openai_key:
        return (
            {
                "data": {
                    "type": "openai_credential",
                    "api_key": openai_key,
                },
            },
            "openai_chat",
            "gpt-4o",
        )
    print(
        "ERROR: set DASHSCOPE_API_KEY or OPENAI_API_KEY before running the "
        "client.",
        file=sys.stderr,
    )
    raise SystemExit(1)


async def step_1_create_credential(
    client: httpx.AsyncClient,
) -> tuple[str, str, str]:
    cred_body, model_type, model_name = _pick_credential_payload()
    resp = await client.post("/credential/", json=cred_body, headers=HEADERS)
    resp.raise_for_status()
    credential_id = resp.json()["credential_id"]
    print(f"[1] credential_id = {credential_id}")
    return credential_id, model_type, model_name


async def step_2_create_agent(client: httpx.AsyncClient) -> str:
    body = {
        "name": "DataMuse",
        "system_prompt": (
            "You are DataMuse, a sales-data analyst.\n"
            "Use SalesProfile to inspect the server-side sales dataset and "
            "SalesBreakdown for grouped analysis. Do not guess figures. "
            "If asked to write a report, use the report_writer skill that "
            "has been installed in the workspace."
        ),
    }
    resp = await client.post("/agent/", json=body, headers=HEADERS)
    resp.raise_for_status()
    agent_id = resp.json()["agent_id"]
    print(f"[2] agent_id      = {agent_id}")
    return agent_id


async def step_3_create_session(
    client: httpx.AsyncClient,
    agent_id: str,
    credential_id: str,
    model_type: str,
    model_name: str,
) -> str:
    body = {
        "agent_id": agent_id,
        "name": "DataMuse demo session",
        "chat_model_config": {
            "type": model_type,
            "credential_id": credential_id,
            "model": model_name,
            "parameters": {},
        },
    }
    resp = await client.post("/sessions/", json=body, headers=HEADERS)
    resp.raise_for_status()
    session_id = resp.json()["session_id"]
    print(f"[3] session_id    = {session_id}")
    return session_id


async def step_4_chat(
    client: httpx.AsyncClient,
    agent_id: str,
    session_id: str,
    prompt: str,
) -> None:
    body = {
        "agent_id": agent_id,
        "session_id": session_id,
        "input": {
            "name": "user",
            "role": "user",
            "content": [{"type": "text", "text": prompt}],
        },
    }
    print(f"\n[4] streaming reply for: {prompt!r}")
    print("-" * 60)

    stream_url = f"/sessions/{session_id}/stream"
    async with client.stream(
        "GET",
        stream_url,
        params={"agent_id": agent_id},
        headers=HEADERS,
        timeout=httpx.Timeout(60.0, read=None),
    ) as resp:
        resp.raise_for_status()

        trigger_resp = await client.post(
            "/chat/",
            json=body,
            headers=HEADERS,
        )
        trigger_resp.raise_for_status()
        print(f"  >> chat run {trigger_resp.json()['status']}")

        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()  # noqa: E203
            if not payload or payload == "[DONE]":
                continue
            event = json.loads(payload)
            etype = event.get("type")
            if etype == "TEXT_BLOCK_DELTA":
                print(event.get("delta", ""), end="", flush=True)
            elif etype == "TOOL_CALL_START":
                print(
                    f"\n  >> calling tool: {event.get('tool_call_name')}",
                    flush=True,
                )
            elif etype == "TOOL_RESULT_END":
                print(
                    f"  >> tool finished: {event.get('state')}",
                    flush=True,
                )
            elif etype == "REPLY_END":
                print()
                break
    print("-" * 60)


async def step_5_list_messages(
    client: httpx.AsyncClient,
    agent_id: str,
    session_id: str,
) -> None:
    resp = await client.get(
        f"/sessions/{session_id}/messages",
        params={"agent_id": agent_id},
        headers=HEADERS,
    )
    resp.raise_for_status()
    data = resp.json()
    msgs = data.get("messages", [])
    print(f"\n[5] persisted messages: {len(msgs)}")
    for msg in msgs:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, list):
            content = " | ".join(
                block.get("text", str(block)) for block in content
            )
        snippet = str(content)[:160].replace("\n", " ")
        print(f"    [{role}] {snippet}")


async def main() -> None:
    print(f"Talking to {BASE_URL} as user {USER_ID!r}")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        cred_id, model_type, model_name = await step_1_create_credential(
            client,
        )
        agent_id = await step_2_create_agent(client)
        session_id = await step_3_create_session(
            client,
            agent_id,
            cred_id,
            model_type,
            model_name,
        )
        await step_4_chat(
            client,
            agent_id,
            session_id,
            "Use SalesProfile to list the dataset columns and row count, "
            "then use SalesBreakdown to summarize revenue by category.",
        )
        await step_5_list_messages(client, agent_id, session_id)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except httpx.ConnectError as exc:
        print(
            f"\nERROR: cannot reach {BASE_URL}.\n"
            "Did you start the service in another terminal? "
            "Run: python main.py",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
