# -*- coding: utf-8 -*-
"""Tutorial 01: Hello AgentScope — Your first Agent.

This tutorial demonstrates:
- Creating a basic Agent with AgentScope 2.0
- Using reply() for blocking responses
- Using reply_stream() for streaming responses

Using OpenAI instead? Swap the 4 model lines in main() for:
    from agentscope.credential import OpenAICredential
    from agentscope.model import OpenAIChatModel
    model = OpenAIChatModel(
        credential=OpenAICredential(api_key=os.environ["OPENAI_API_KEY"]),
        model="gpt-4o",
    )
"""
# pylint: disable=missing-function-docstring
import asyncio
import os

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.event import EventType
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel


async def main() -> None:
    agent = Agent(
        name="DataMuse",
        system_prompt=(
            "You are DataMuse, a friendly data analysis assistant. "
            "Keep responses concise and actionable."
        ),
        model=DashScopeChatModel(
            credential=DashScopeCredential(
                api_key=os.environ["DASHSCOPE_API_KEY"],
            ),
            model="qwen-plus",
        ),
    )

    # --- reply(): blocking, returns the full Msg when done ---
    print("\n--- reply() ---")
    result = await agent.reply(
        UserMsg(
            name="user",
            content="What chart type best shows trends over time? "
            "Answer in 2 sentences.",
        ),
    )
    print(result.get_text_content())

    # --- reply_stream(): async iterator, yields events as they arrive ---
    print("\n--- reply_stream() ---")
    async for event in agent.reply_stream(
        UserMsg(name="user", content="And for comparing categories?"),
    ):
        if event.type == EventType.TEXT_BLOCK_DELTA:
            print(event.delta, end="", flush=True)
    print()


if __name__ == "__main__":
    asyncio.run(main())
