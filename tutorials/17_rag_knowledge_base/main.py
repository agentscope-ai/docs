# -*- coding: utf-8 -*-
"""Tutorial 17: index private knowledge and attach RAG to DataMuse."""
import asyncio
import os
from typing import Literal

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.embedding import DashScopeEmbeddingModel
from agentscope.message import TextBlock, UserMsg
from agentscope.middleware import RAGMiddleware
from agentscope.model import DashScopeChatModel
from agentscope.rag import (
    ApproxTokenChunker,
    KnowledgeBase,
    QdrantStore,
    TextParser,
)
from agentscope.tool import Toolkit


DOCUMENTS: dict[str, bytes] = {
    "metric-definitions.md": (
        b"# DataMuse metric definitions\n\n"
        b"Revenue is the sum of the total column after discounts. "
        b"Average order value is revenue divided by order count. "
        b"Every report must state the date range and grouping dimension.\n"
    ),
    "report-policy.md": (
        b"# DataMuse report policy\n\n"
        b"A weekly sales report must include revenue, order count, average "
        b"order value, the strongest segment, and one recommendation. "
        b"All numeric claims must come from a calculation tool.\n"
    ),
}


async def index_documents(knowledge: KnowledgeBase) -> None:
    """Parse, chunk, embed, and insert the tutorial documents."""
    parser = TextParser()
    chunker = ApproxTokenChunker(
        parameters=ApproxTokenChunker.Parameters(
            chunk_size=128,
            overlap=16,
        ),
    )
    for filename, content in DOCUMENTS.items():
        sections = await parser.parse(file=content, filename=filename)
        chunks = await chunker.chunk(sections)
        document_id = await knowledge.insert_document(
            chunks,
            document_metadata={"filename": filename},
        )
        print(f"indexed {filename}: {document_id} ({len(chunks)} chunks)")


async def show_search(knowledge: KnowledgeBase) -> None:
    """Print the evidence returned before involving a chat model."""
    results = await knowledge.search(
        queries=["What must a weekly sales report include?"],
        top_k=2,
    )
    print("\nDirect search evidence:")
    for result in results:
        content = result.chunk.content
        text = content.text if isinstance(content, TextBlock) else "<data>"
        print(f"  score={result.score:.3f}: {text.strip()}")


async def ask_with_rag(
    name: str,
    mode: Literal["static", "agentic"],
    knowledge: KnowledgeBase,
    chat_model: DashScopeChatModel,
) -> None:
    """Build one reranked RAG mode and ask a policy question."""
    rag = RAGMiddleware(
        knowledge_bases=[knowledge],
        parameters=RAGMiddleware.Parameters(
            mode=mode,
            top_k=2,
            rerank_candidate_k=4,
        ),
        rerank_model=chat_model,
    )
    agent = Agent(
        name=name,
        system_prompt=(
            "You are DataMuse. Answer from retrieved company knowledge. "
            "Do not invent policy or numeric results."
        ),
        model=chat_model,
        toolkit=Toolkit(tools=await rag.list_tools()),
        middlewares=[rag],
    )
    reply = await agent.reply(
        UserMsg(
            name="user",
            content="What must our weekly sales report contain?",
        ),
    )
    print(f"\n[{mode}] {reply.get_text_content()}")


async def main() -> None:
    """Run indexing, direct search, and both Agent RAG modes."""
    api_key = os.environ["DASHSCOPE_API_KEY"]
    credential = DashScopeCredential(api_key=api_key)
    embedding_model = DashScopeEmbeddingModel(
        credential=credential,
        model="text-embedding-v4",
        dimensions=1024,
    )
    chat_model = DashScopeChatModel(
        credential=credential,
        model="qwen-plus",
        stream=False,
    )

    store = QdrantStore(location=":memory:")
    async with store:
        knowledge = KnowledgeBase(
            name="datamuse-handbook",
            description="DataMuse metric definitions and report policy.",
            embedding_model=embedding_model,
            vector_store=store,
            collection="datamuse-handbook",
        )
        await index_documents(knowledge)
        await show_search(knowledge)
        await ask_with_rag(
            "DataMuse_StaticRAG",
            "static",
            knowledge,
            chat_model,
        )
        await ask_with_rag(
            "DataMuse_AgenticRAG",
            "agentic",
            knowledge,
            chat_model,
        )


if __name__ == "__main__":
    asyncio.run(main())
