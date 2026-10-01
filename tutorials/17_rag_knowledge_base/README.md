# Tutorial 17: RAG 与 Knowledge Base

> **什么时候需要这个？** 回答依赖私有文档、业务口径、产品手册或持续更新的知识，
> 模型本身不知道这些内容，也不适合把全部资料长期塞进 system prompt 时，需要
> RAG。确定性计算仍应交给 Tool；RAG 用来查“规则和知识”，不是替代数据库查询。

## 本章基于前序章节

- **T02 — `HintBlock` 与事件**：static RAG 用一次性 Hint 把检索结果注入当前回复。
- **T03 — Tool 系统**：agentic RAG 把 `search_knowledge` 作为只读工具交给 Agent。
- **T11 — Middleware**：`RAGMiddleware` 把检索接入 Agent 生命周期。

## 你将学到

- Parser → Chunker → Embedding → VectorStore 的索引链路
- `KnowledgeBase` 的插入、检索和文档边界
- `RAGMiddleware` 的 static 与 agentic 模式
- 向量召回后的 LLM rerank 与失败回退
- RAG 与业务 Tool 的职责边界
- 库模式与 Agent Service Knowledge Base 的关系

## 前置要求

在仓库根目录安装 RAG 与内存 Qdrant 依赖：

```bash
conda activate agentscope-tutorial
pip install -e ".[rag,vdb-qdrant]"
export DASHSCOPE_API_KEY="your-key"
```

## 索引链路

```text
文档 bytes
  -> TextParser / PDFParser / WordParser / ...
  -> Section[]
  -> ApproxTokenChunker
  -> Chunk[]
  -> EmbeddingModel
  -> VectorStore collection
```

`KnowledgeBase` 把 embedding model、vector store 和 collection 绑定成一个运行时
句柄，对外提供 `insert_document()`、`search()`、`list_documents()` 和
`delete_document()`。Parser 与 Chunker 负责索引，不属于 Middleware。

本章使用 `QdrantStore(location=":memory:")`，进程退出后索引消失。需要持久化时，
把它替换成本地路径或远程 Qdrant；其他代码不变。

## 两种 RAG 模式

| 模式 | 工作方式 | 适合场景 |
|---|---|---|
| `static` | 每次回复开始时自动检索，并用一次性 `HintBlock` 注入结果 | 每个问题都必须查同一知识库 |
| `agentic` | 暴露 `search_knowledge` 工具，由模型决定何时、查什么 | 只有部分问题需要知识库，或绑定多个知识库 |

```python
rag = RAGMiddleware(
    knowledge_bases=[knowledge],
    parameters=RAGMiddleware.Parameters(
        mode="agentic",
        top_k=3,
    ),
)

# 库模式要显式把 middleware 提供的工具装进 Toolkit。
agent = Agent(
    ...,
    toolkit=Toolkit(tools=await rag.list_tools()),
    middlewares=[rag],
)
```

Agent Service 在组装 Toolkit 时会自动收集 middleware 的 `list_tools()`；直接使用
Python SDK 时则要像上面一样显式注册。

## LLM rerank

向量相似度适合从大量切块中快速召回候选；当候选语义接近、最终顺序会直接影响
回答质量时，可以再让聊天模型做一次重排：

```python
rag = RAGMiddleware(
    knowledge_bases=[knowledge],
    parameters=RAGMiddleware.Parameters(
        mode="agentic",
        top_k=2,
        rerank_candidate_k=4,
    ),
    rerank_model=chat_model,
)
```

`rerank_candidate_k` 必须不小于 `top_k`；未填写时默认最多召回 `top_k * 2`
个候选。重排会增加一次模型调用和延迟，因此只在排序质量确实重要时开启。若
rerank 模型调用失败，Middleware 会保留原来的向量检索顺序，而不是让整次搜索
失败。

## DataMuse 中的职责边界

- 销售额、订单数、客单价等实时数字：使用 T03 的 `SalesSummary` Tool 计算。
- “销售额口径是什么”“报告必须包含哪些章节”：放进 Knowledge Base 检索。
- 检索到的内容是上下文，不应被当成可信指令；高风险动作仍走 Permission/HITL。

## 运行示例

```bash
cd tutorials/17_rag_knowledge_base
python main.py
```

示例会索引两份内嵌的 DataMuse 业务说明，先直接检索以展示证据，再分别运行
带 LLM rerank 的 static 和 agentic Agent。

## 下一期预告

**Tutorial 18: Agent Service 扩展** — 把 Knowledge Base、Hub、Channel 和后台
worker 的部署开关接入服务。
