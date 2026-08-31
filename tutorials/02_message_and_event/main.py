# -*- coding: utf-8 -*-
"""Tutorial 02: Message & Event — The Agent communication protocol.

This tutorial demonstrates:
- Msg structure and ContentBlock types
- Event lifecycle (start → delta → end)
- Building a complete message from an event stream via append_event()

Using OpenAI? Swap the 4 model lines in main() — see T01 README.
"""
# pylint: disable=missing-function-docstring
import asyncio
import os
from collections import Counter

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.event import EventType
from agentscope.message import UserMsg, AssistantMsg
from agentscope.model import DashScopeChatModel


# =========================================================================
# Example 1: Inspect Msg structure
# =========================================================================
async def example_msg_structure() -> None:
    print("\n--- Example 1: Msg structure ---")

    msg = UserMsg(name="alice", content="What is a histogram?")

    print(f"id        = {msg.id}")
    print(f"name      = {msg.name}")
    print(f"role      = {msg.role}")
    print(f"#blocks   = {len(msg.content)}")
    for i, block in enumerate(msg.content):
        print(f"block[{i}] = type={block.type} text={block.text!r}")

    print(f"get_text_content() -> {msg.get_text_content()!r}")
    print(f"has_content_blocks('text') -> {msg.has_content_blocks('text')}")


# =========================================================================
# Example 2: Observe the event lifecycle
# =========================================================================
async def example_event_types(agent: Agent) -> None:
    print("\n--- Example 2: Event lifecycle ---")

    msg = UserMsg(
        name="user",
        content="Explain mean vs median vs mode in 2 sentences.",
    )

    counts: Counter[str] = Counter()
    async for event in agent.reply_stream(msg):
        counts[event.type] += 1
        # Print one line per non-delta event to show the start→...→end pattern
        if not event.type.endswith("_delta"):
            print(f"  {event.type}")

    print("\nEvent counts:")
    for etype, n in counts.items():
        print(f"  {etype}: {n}")


# =========================================================================
# Example 3: Reconstruct a Msg from the event stream
# =========================================================================
async def example_reconstruct_msg(agent: Agent) -> None:
    print("\n--- Example 3: Reconstruct Msg via append_event() ---")

    msg = UserMsg(
        name="user",
        content="Name the top 3 Python data-analysis libraries.",
    )

    result_msg: AssistantMsg | None = None
    text_buffer = ""

    async for event in agent.reply_stream(msg):
        if event.type == EventType.REPLY_START:
            result_msg = AssistantMsg(
                name=event.name,
                content=[],
                id=event.reply_id,
            )
        if event.type == EventType.TEXT_BLOCK_DELTA:
            text_buffer += event.delta
            print(event.delta, end="", flush=True)
        if result_msg is not None:
            result_msg.append_event(event)
    print()

    assert result_msg is not None
    print(f"\nreconstructed.id        = {result_msg.id}")
    print(f"reconstructed.#blocks   = {len(result_msg.content)}")
    print(
        f"reconstructed text == streamed text -> "
        f"{result_msg.get_text_content() == text_buffer}",
    )


async def main() -> None:
    await example_msg_structure()

    agent = Agent(
        name="DataMuse",
        system_prompt="You are DataMuse. Give concise answers.",
        model=DashScopeChatModel(
            credential=DashScopeCredential(
                api_key=os.environ["DASHSCOPE_API_KEY"],
            ),
            model="qwen-plus",
        ),
    )

    await example_event_types(agent)
    await example_reconstruct_msg(agent)


if __name__ == "__main__":
    asyncio.run(main())
