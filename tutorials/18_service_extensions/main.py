# -*- coding: utf-8 -*-
"""Tutorial 18: start an Agent Service with RAG and capability hubs."""
from pathlib import Path

import uvicorn

from agentscope.app import create_app
from agentscope.app.hub import ClawSkillHub, GitHubMCPHub
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.rag.knowledge_base_manager import CollectionPerKbManager
from agentscope.app.storage import AsyncSQLAlchemyStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.rag import ApproxTokenChunker, QdrantStore


TUTORIAL_DIR = Path(__file__).resolve().parent
storage = AsyncSQLAlchemyStorage(
    f"sqlite+aiosqlite:///{TUTORIAL_DIR / 'agent_service.db'}",
)
vector_store = QdrantStore(location=":memory:")

app = create_app(
    storage=storage,
    message_bus=InMemoryMessageBus(),
    workspace_manager=LocalWorkspaceManager(
        basedir=str(TUTORIAL_DIR / "workspaces"),
    ),
    knowledge_base_manager=CollectionPerKbManager(
        storage=storage,
        vector_store=vector_store,
    ),
    knowledge_chunkers=[ApproxTokenChunker],
    mcp_hubs=[GitHubMCPHub()],
    skill_hubs=[ClawSkillHub()],
    enable_scheduler=True,
    enable_index_worker=True,
    enable_channel_worker=True,
    title="AgentScope Extended Service",
)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
