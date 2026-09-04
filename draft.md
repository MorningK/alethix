梳理一个基于LangChain + Qdrant + Fastapi 的智能阅读检索解答的智能体。主要功能流程包括了：上传一篇文档，解析完成后，用户可以基于一篇或多篇文档进行提问，智能体进行多轮的检索和调查，最终回答用户的问题。该智能体的特点是：和普通rag检索往往只查一次不同，支持智能体根据初次检索的信息进行调研，然后进一步判断是否需要根据已有的情报多次进行检索，直到得出结论

---

下面给你梳理一套 **基于 LangChain / LangGraph + Qdrant + FastAPI 的智能阅读检索解答智能体（Agentic / Iterative RAG）** 的完整方案。

这个智能体的核心定位不是普通 RAG，而是：

> 用户提问后，智能体先检索一次，然后根据检索到的信息判断证据是否充分；如果不充分，会继续生成新的检索问题，再次检索、继续调研，直到形成足够证据，再给出最终答案。

可以理解为：

```text
普通 RAG：
用户问题 -> 一次检索 -> TopK -> 生成答案

智能调研 RAG：
用户问题 -> 拆解问题 -> 检索 -> 分析证据 -> 判断是否足够
          -> 不够则生成新查询 -> 再检索 -> 再分析
          -> 直到证据充分 -> 生成最终答案
```

---

# 一、系统目标

这个智能体主要解决以下场景：

```text
用户上传一篇或多篇文档，例如：
PDF
Word
Markdown
TXT
网页文本
财报
论文
合同
产品说明书
技术文档

然后基于这些文档进行提问：
这篇文档的核心结论是什么？
A 文档和 B 文档对同一个问题的说法是否一致？
这个方案的缺点有哪些？
根据多份材料判断某个结论是否成立？
请结合第 3 篇和第 5 篇文档回答问题。
```

系统需要支持：

1. 文档上传与解析。
2. 文档切片、向量化、入库。
3. 用户基于一篇或多篇文档提问。
4. 智能体自动多轮检索。
5. 智能体判断证据是否充分。
6. 必要时继续追查。
7. 最终给出有引用、有依据的答案。

---

# 二、总体架构

可以采用如下架构：

```text
                         ┌──────────────────────────────┐
                         │           前端 / 用户          │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │           FastAPI 服务        │
                         │  文档上传 / 会话问答 / 查询状态  │
                         └──────┬───────────────┬───────┘
                                │               │
                 ┌──────────────┘               └──────────────┐
                 ▼                                             ▼
   ┌──────────────────────────┐                 ┌──────────────────────────────┐
   │      文档处理服务         │                 │       智能调研 Agent 服务      │
   │  解析 / 清洗 / 分块 /入库 │                 │ LangChain / LangGraph 状态机  │
   └──────┬───────────────────┘                 └──────┬───────────────────────┘
          │                                            │
          ▼                                            ▼
┌────────────────────┐                      ┌────────────────────┐
│      Qdrant        │                      │       LLM          │
│ 向量库 + 元数据过滤 │◄────────────────────►│  问题分析/证据判断   │
└────────────────────┘                      └────────────────────┘
```

核心组件：

| 组件 | 作用 |
|---|---|
| FastAPI | 提供文档上传、问答、会话、任务状态、事件流接口 |
| LangChain / LangGraph | 构建多轮调研智能体状态机 |
| Qdrant | 存储文档切片向量、原文、元数据，支持按文档过滤 |
| Document Parser | 解析 PDF、Word、Markdown、TXT 等 |
| Embedding Model | 将文本切片转成向量 |
| LLM | 问题改写、证据分析、是否继续检索判断、最终回答 |
| Redis / PostgreSQL | 可选，存储会话、任务状态、调研轨迹 |

---

# 三、核心业务流程

整个系统可以拆成两大流程：

```text
1. 文档入库流程
2. 智能问答调研流程
```

---

# 3.1 文档入库流程

```text
用户上传文档
  ↓
FastAPI 接收文件
  ↓
保存原始文件 / 生成 document_id
  ↓
异步解析文档
  ↓
提取正文、标题、页码、段落结构
  ↓
清洗文本
  ↓
按语义或固定长度切片
  ↓
生成 chunk_id
  ↓
调用 Embedding 模型生成向量
  ↓
写入 Qdrant
  ↓
更新文档状态为已完成
```

文档状态可以设计为：

```text
uploaded      已上传
parsing       解析中
chunking      切片中
embedding     向量化中
ready         可检索
failed        失败
```

---

# 3.2 智能问答调研流程

这是整个智能体的核心。

```text
用户提问
  ↓
创建问答会话
  ↓
初始化问题上下文
  ↓
Agent 第一次理解问题
  ↓
生成初始检索查询
  ↓
在 Qdrant 中检索
  ↓
LLM 阅读检索结果
  ↓
提取有效证据
  ↓
判断：
    证据是否足够回答？
    是否存在信息缺口？
    是否需要继续调研？
  ↓
如果不够：
    生成新的子问题 / 新查询
    再次检索
    继续累积证据
  ↓
如果足够：
    综合所有证据
    生成最终答案
    返回引用来源
```

可以抽象为一个循环：

```python
while not enough_evidence and iteration < max_iterations:
    retrieve()
    analyze()
    decide()
```

---

# 四、Qdrant 数据模型设计

建议为每篇文档的每个切片建立一条 Qdrant Point。

## Collection 名称

例如：

```text
document_chunks
```

## Vector

```json
{
  "dense_vector": [0.012, -0.034, ...]
}
```

维度取决于 Embedding 模型：

| Embedding 模型 | 维度示例 |
|---|---:|
| bge-small | 512 |
| bge-base | 768 |
| bge-large | 1024 |
| bge-m3 dense | 1024 |
| OpenAI text-embedding-3-small | 1536 |
| OpenAI text-embedding-3-large | 3072 |

---

## Payload 设计

每条切片建议包含：

```json
{
  "doc_id": "doc_001",
  "user_id": "user_123",
  "filename": "2026_ai_report.pdf",
  "title": "AI 行业报告",
  "chunk_id": "doc_001_chunk_00012",
  "chunk_index": 12,
  "content": "这里是切片原文",
  "page": 5,
  "section": "3.2 行业趋势",
  "source": "pdf",
  "language": "zh",
  "created_at": "2026-09-04T10:00:00Z"
}
```

重点字段：

| 字段 | 作用 |
|---|---|
| `doc_id` | 用于限定只查某一篇或某几篇文档 |
| `user_id` | 多用户隔离 |
| `chunk_id` | 唯一引用来源 |
| `chunk_index` | 方便召回相邻上下文 |
| `page` | 用于答案引用展示 |
| `section` | 用于答案引用展示 |
| `content` | 原文，用于 LLM 阅读 |

---

# 五、FastAPI 接口设计

可以设计如下接口。

---

## 1. 上传文档

```http
POST /documents/upload
```

请求：

```multipart/form-data
file: example.pdf
user_id: user_123
```

返回：

```json
{
  "document_id": "doc_001",
  "filename": "example.pdf",
  "status": "parsing"
}
```

---

## 2. 查询文档解析状态

```http
GET /documents/{document_id}/status
```

返回：

```json
{
  "document_id": "doc_001",
  "status": "ready",
  "chunk_count": 235
}
```

---

## 3. 获取文档列表

```http
GET /documents?user_id=user_123
```

返回：

```json
[
  {
    "document_id": "doc_001",
    "filename": "example.pdf",
    "status": "ready",
    "chunk_count": 235,
    "created_at": "2026-09-04T10:00:00Z"
  }
]
```

---

## 4. 提问

```http
POST /ask
```

请求：

```json
{
  "user_id": "user_123",
  "session_id": "sess_001",
  "question": "这篇文档里提到的主要风险有哪些？",
  "document_ids": ["doc_001"],
  "max_iterations": 5
}
```

如果 `document_ids` 为空，则可以在用户所有文档范围内检索。

返回：

```json
{
  "session_id": "sess_001",
  "question": "这篇文档里提到的主要风险有哪些？",
  "answer": "根据文档内容，主要风险包括...",
  "iterations": [
    {
      "iteration": 1,
      "queries": ["文档中提到的风险因素"],
      "retrieved_chunk_count": 8,
      "decision": "not_enough"
    },
    {
      "iteration": 2,
      "queries": ["风险 合规 数据安全 法律风险"],
      "retrieved_chunk_count": 10,
      "decision": "enough"
    }
  ],
  "citations": [
    {
      "doc_id": "doc_001",
      "chunk_id": "doc_001_chunk_00005",
      "filename": "example.pdf",
      "page": 3,
      "section": "风险分析",
      "content": "本项目可能面临数据合规风险..."
    }
  ]
}
```

---

## 5. 流式返回调研过程

如果需要更好的体验，可以用 SSE：

```http
POST /ask/stream
```

返回事件流：

```text
event: started
data: {"session_id": "sess_001"}

event: iteration
data: {"iteration": 1, "queries": ["主要风险"]}

event: retrieved
data: {"iteration": 1, "chunk_count": 8}

event: reasoning
data: {"decision": "not_enough", "reason": "缺少具体风险类别"}

event: iteration
data: {"iteration": 2, "queries": ["合规风险 数据安全风险"]}

event: final_answer
data: {"answer": "...", "citations": [...]}
```

---

# 六、智能体状态机设计

这里建议使用 **LangGraph**，而不是简单的 LangChain AgentExecutor。

原因是普通 AgentExecutor 可控性较差，而多轮调研需要明确的状态流转：

```text
规划问题
  ↓
检索证据
  ↓
分析证据
  ↓
判断是否足够
  ↓
不足则继续规划
  ↓
足够则生成答案
```

---

## 6.1 状态定义

```python
from typing import TypedDict, List, Literal, Optional
from pydantic import BaseModel


class Citation(BaseModel):
    doc_id: str
    chunk_id: str
    filename: str
    page: Optional[int] = None
    section: Optional[str] = None
    content: str
    score: Optional[float] = None


class RetrievedChunk(BaseModel):
    doc_id: str
    chunk_id: str
    content: str
    score: float
    filename: str
    page: Optional[int] = None
    section: Optional[str] = None


class IterationRecord(BaseModel):
    iteration: int
    queries: List[str]
    retrieved_chunks: List[RetrievedChunk]
    reasoning: str
    decision: Literal["continue", "answer"]


class AgentState(TypedDict):
    user_id: str
    session_id: str
    question: str
    document_ids: List[str]

    iteration: int
    max_iterations: int

    queries: List[str]
    searched_queries: List[str]

    findings: List[str]
    citations: List[Citation]

    iterations: List[IterationRecord]

    status: Literal[
        "planning",
        "retrieving",
        "analyzing",
        "deciding",
        "answering",
        "done",
        "failed"
    ]

    final_answer: str
```

---

# 七、Agent 节点设计

可以把智能体拆成 5 个节点。

```text
plan_queries
    ↓
retrieve_documents
    ↓
analyze_evidence
    ↓
decide_next_step
    ↓
final_answer
```

---

## 7.1 plan_queries：规划检索问题

这个节点负责根据用户问题和当前已知信息，生成新的检索查询。

第一次调用时：

```text
输入：
用户原始问题
```

后续调用时：

```text
输入：
用户原始问题
已有发现
信息缺口
历史查询
```

输出：

```json
{
  "queries": [
    "文档中提到的主要风险因素",
    "合规风险 数据安全 法律责任"
  ]
}
```

---

## 7.2 retrieve_documents：检索 Qdrant

这个节点根据 `queries` 到 Qdrant 中检索。

如果用户指定了 `document_ids`，则必须加过滤条件。

例如只查这几篇文档：

```python
Filter(
    must=[
        FieldCondition(
            key="doc_id",
            match=MatchAny(any=document_ids)
        )
    ]
)
```

如果没指定，则可以用：

```python
Filter(
    must=[
        FieldCondition(
            key="user_id",
            match=MatchValue(value=user_id)
        )
    ]
)
```

---

## 7.3 analyze_evidence：分析证据

LLM 阅读检索结果，输出：

```json
{
  "findings": [
    "文档第 3 页提到数据合规风险",
    "文档第 7 页提到供应链中断风险"
  ],
  "used_chunk_ids": [
    "doc_001_chunk_00005",
    "doc_001_chunk_00012"
  ],
  "reasoning": "当前检索结果已经覆盖部分风险，但缺少风险等级说明"
}
```

---

## 7.4 decide_next_step：判断是否继续

这是整个智能体区别于普通 RAG 的关键。

LLM 输入：

```text
用户问题
当前已知发现
已使用证据
历史查询
当前轮次
最大轮次限制
```

输出：

```json
{
  "is_sufficient": false,
  "missing_information": "缺少风险等级和应对措施",
  "new_queries": [
    "风险等级 高 中 低",
    "风险应对措施 缓解方案"
  ]
}
```

或者：

```json
{
  "is_sufficient": true,
  "reason": "已有证据足以回答用户问题",
  "new_queries": []
}
```

---

## 7.5 final_answer：生成最终答案

最终答案必须基于累积证据，而不是自由发挥。

输出结构建议：

```json
{
  "answer": "...",
  "citations": [
    {
      "doc_id": "doc_001",
      "chunk_id": "doc_001_chunk_00005",
      "quote": "原文引用"
    }
  ],
  "confidence": "high"
}
```

---

# 八、关键 Prompt 设计

---

## 8.1 查询规划 Prompt

```text
你是一个文档调研智能体。

用户问题：
{question}

当前已经知道的信息：
{findings}

已经检索过的问题：
{searched_queries}

当前信息缺口：
{missing_information}

请你生成 1 到 3 个新的检索查询，用于在文档库中继续查找证据。

要求：
1. 查询要简洁，适合向量检索。
2. 不要重复已经检索过的问题。
3. 如果用户问题涉及多篇文档，需要分别考虑不同文档中的相关表述。
4. 优先查找事实、结论、数据、定义、原因、风险、方案等关键信息。
5. 只输出 JSON，不要输出解释。

输出格式：
{
  "queries": ["查询1", "查询2"]
}
```

---

## 8.2 证据分析 Prompt

```text
你是一个严谨的文档分析助手。

用户问题：
{question}

检索到的文档片段：
{retrieved_context}

请你从这些片段中提取与用户问题相关的事实。

要求：
1. 只能使用给定片段中的信息。
2. 每条发现必须简洁明确。
3. 如果片段之间存在冲突，请指出冲突。
4. 不要编造不存在的信息。
5. 输出 JSON。

输出格式：
{
  "findings": ["发现1", "发现2"],
  "used_chunk_ids": ["chunk_id_1", "chunk_id_2"],
  "conflicts": ["冲突1"],
  "reasoning": "分析过程"
}
```

---

## 8.3 是否继续调研 Prompt

```text
你是一个调研决策器。

用户问题：
{question}

当前已知发现：
{findings}

已经检索过的问题：
{searched_queries}

当前轮次：
{iteration}

最大轮次：
{max_iterations}

请判断当前证据是否足够回答用户问题。

如果足够：
- is_sufficient 为 true
- new_queries 为空数组

如果不足：
- is_sufficient 为 false
- 说明 missing_information
- 生成 1 到 3 个新的检索查询

只输出 JSON：

{
  "is_sufficient": true/false,
  "missing_information": "缺少的信息",
  "new_queries": ["新查询1", "新查询2"],
  "reason": "判断原因"
}
```

---

## 8.4 最终回答 Prompt

```text
你是一个基于文档证据回答问题的助手。

用户问题：
{question}

已收集到的证据：
{findings}

相关原文片段：
{evidence_context}

请根据以上证据回答用户问题。

要求：
1. 答案必须基于证据，不能编造。
2. 如果证据不足，要明确说明不足。
3. 如果多篇文档存在冲突，要分别说明。
4. 回答中需要给出引用来源。
5. 语言要清晰、结构化。

输出格式：
{
  "answer": "最终回答",
  "confidence": "high/medium/low",
  "citations": [
    {
      "chunk_id": "chunk_id",
      "quote": "原文引用"
    }
  ]
}
```

---

# 九、核心代码示例

下面给出一个可落地的代码骨架。

---

## 9.1 Qdrant 初始化

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


class QdrantService:
    def __init__(self, url: str, collection_name: str, vector_size: int):
        self.client = QdrantClient(url=url)
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.ensure_collection()

    def ensure_collection(self):
        collections = [c.name for c in self.client.get_collections().collections]

        if self.collection_name not in collections:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "dense": VectorParams(
                        size=self.vector_size,
                        distance=Distance.COSINE
                    )
                }
            )
```

---

## 9.2 写入文档切片

```python
from qdrant_client.models import PointStruct


def upsert_chunks(
    qdrant: QdrantService,
    chunks: list[dict],
    embeddings: list[list[float]]
):
    points = []

    for chunk, vector in zip(chunks, embeddings):
        points.append(
            PointStruct(
                id=chunk["chunk_id"],
                vector={
                    "dense": vector
                },
                payload={
                    "doc_id": chunk["doc_id"],
                    "user_id": chunk["user_id"],
                    "filename": chunk["filename"],
                    "chunk_index": chunk["chunk_index"],
                    "content": chunk["content"],
                    "page": chunk.get("page"),
                    "section": chunk.get("section"),
                    "created_at": chunk["created_at"]
                }
            )
        )

    qdrant.client.upsert(
        collection_name=qdrant.collection_name,
        points=points
    )
```

---

## 9.3 检索函数

```python
from qdrant_client.models import (
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny
)


def retrieve_from_qdrant(
    qdrant: QdrantService,
    query_vector: list[float],
    user_id: str,
    document_ids: list[str] | None = None,
    top_k: int = 10
):
    filters = [
        FieldCondition(
            key="user_id",
            match=MatchValue(value=user_id)
        )
    ]

    if document_ids:
        filters.append(
            FieldCondition(
                key="doc_id",
                match=MatchAny(any=document_ids)
            )
        )

    results = qdrant.client.search(
        collection_name=qdrant.collection_name,
        query_vector=query_vector,
        query_filter=Filter(must=filters),
        with_payload=True,
        limit=top_k
    )

    chunks = []

    for result in results:
        payload = result.payload

        chunks.append({
            "chunk_id": result.id,
            "doc_id": payload.get("doc_id"),
            "filename": payload.get("filename"),
            "content": payload.get("content"),
            "page": payload.get("page"),
            "section": payload.get("section"),
            "score": result.score
        })

    return chunks
```

---

## 9.4 多查询检索

智能体每轮可能生成多个查询，需要合并结果。

```python
def retrieve_with_queries(
    qdrant: QdrantService,
    embedder,
    queries: list[str],
    user_id: str,
    document_ids: list[str] | None = None,
    top_k_per_query: int = 8
):
    all_chunks = {}

    for query in queries:
        query_vector = embedder.embed_query(query)

        chunks = retrieve_from_qdrant(
            qdrant=qdrant,
            query_vector=query_vector,
            user_id=user_id,
            document_ids=document_ids,
            top_k=top_k_per_query
        )

        for chunk in chunks:
            chunk_id = chunk["chunk_id"]

            if chunk_id not in all_chunks:
                all_chunks[chunk_id] = chunk
            else:
                old_score = all_chunks[chunk_id]["score"]
                new_score = chunk["score"]

                if new_score > old_score:
                    all_chunks[chunk_id] = chunk

    sorted_chunks = sorted(
        all_chunks.values(),
        key=lambda x: x["score"],
        reverse=True
    )

    return sorted_chunks
```

---

# 十、智能体主循环示例

下面是一个简化但非常实用的主循环，不一定马上上 LangGraph，也可以先用这个结构跑通。

```python
class ResearchAgent:
    def __init__(
        self,
        llm,
        qdrant: QdrantService,
        embedder,
        max_iterations: int = 5
    ):
        self.llm = llm
        self.qdrant = qdrant
        self.embedder = embedder
        self.max_iterations = max_iterations

    async def answer(
        self,
        user_id: str,
        session_id: str,
        question: str,
        document_ids: list[str] | None = None
    ):
        state = {
            "user_id": user_id,
            "session_id": session_id,
            "question": question,
            "document_ids": document_ids or [],
            "iteration": 0,
            "findings": [],
            "searched_queries": [],
            "citations": [],
            "iterations": []
        }

        while state["iteration"] < self.max_iterations:
            state["iteration"] += 1

            # 1. 规划查询
            queries = await self.plan_queries(state)

            # 去重
            queries = [
                q for q in queries
                if q not in state["searched_queries"]
            ]

            if not queries:
                break

            state["searched_queries"].extend(queries)

            # 2. 检索
            chunks = retrieve_with_queries(
                qdrant=self.qdrant,
                embedder=self.embedder,
                queries=queries,
                user_id=user_id,
                document_ids=document_ids,
                top_k_per_query=8
            )

            # 3. 分析证据
            analysis = await self.analyze_evidence(state, chunks)

            # 4. 判断是否足够
            decision = await self.decide_next_step(state, analysis)

            state["iterations"].append({
                "iteration": state["iteration"],
                "queries": queries,
                "retrieved_chunk_count": len(chunks),
                "decision": decision
            })

            if decision["is_sufficient"]:
                break

        # 5. 生成最终答案
        final_result = await self.final_answer(state)

        return final_result
```

---

# 十一、节点函数示例

下面给出关键函数的伪代码。

---

## 11.1 规划查询

```python
async def plan_queries(self, state: dict) -> list[str]:
    prompt = f"""
你是一个文档调研智能体。

用户问题：
{state['question']}

当前已知信息：
{state['findings']}

已经检索过的问题：
{state['searched_queries']}

请生成 1 到 3 个新的检索查询。

只输出 JSON：
{{
  "queries": ["查询1", "查询2"]
}}
"""

    result = await self.llm.ainvoke(prompt)
    return result["queries"]
```

---

## 11.2 分析证据

```python
async def analyze_evidence(self, state: dict, chunks: list[dict]) -> dict:
    context = "\n\n".join([
        f"[{chunk['chunk_id']}]\n{chunk['content']}"
        for chunk in chunks
    ])

    prompt = f"""
用户问题：
{state['question']}

检索到的文档片段：
{context}

请提取与问题相关的事实。

只输出 JSON：
{{
  "findings": ["发现1", "发现2"],
  "used_chunk_ids": ["chunk_id"],
  "reasoning": "分析过程"
}}
"""

    return await self.llm.ainvoke(prompt)
```

---

## 11.3 判断是否继续

```python
async def decide_next_step(self, state: dict, analysis: dict) -> dict:
    prompt = f"""
用户问题：
{state['question']}

当前发现：
{analysis['findings']}

已检索问题：
{state['searched_queries']}

当前轮次：
{state['iteration']}

最大轮次：
{self.max_iterations}

请判断证据是否足够回答用户问题。

只输出 JSON：
{{
  "is_sufficient": true/false,
  "missing_information": "缺少什么",
  "new_queries": ["新查询"],
  "reason": "判断原因"
}}
"""

    decision = await self.llm.ainvoke(prompt)

    state["findings"].extend(analysis["findings"])

    return decision
```

---

## 11.4 最终回答

```python
async def final_answer(self, state: dict) -> dict:
    prompt = f"""
用户问题：
{state['question']}

已收集证据：
{state['findings']}

请根据证据回答用户问题。

要求：
1. 不能编造。
2. 如果证据不足，要明确说明。
3. 输出结构化答案。
4. 给出引用。
"""

    result = await self.llm.ainvoke(prompt)

    return {
        "session_id": state["session_id"],
        "question": state["question"],
        "answer": result["answer"],
        "citations": result.get("citations", []),
        "iterations": state["iterations"]
    }
```

---

# 十二、FastAPI 示例

```python
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel


app = FastAPI()


class AskRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    document_ids: list[str] | None = None
    max_iterations: int = 5


@app.post("/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Form(...)
):
    document_id = create_document_record(user_id, file.filename)

    background_tasks.add_task(
        process_document_task,
        document_id=document_id,
        user_id=user_id,
        file=file
    )

    return {
        "document_id": document_id,
        "filename": file.filename,
        "status": "parsing"
    }


@app.post("/ask")
async def ask(req: AskRequest):
    agent = get_research_agent()

    result = await agent.answer(
        user_id=req.user_id,
        session_id=req.session_id,
        question=req.question,
        document_ids=req.document_ids
    )

    return result
```

---

# 十三、文档解析与切片建议

文档解析质量会直接影响智能体效果。

---

## 13.1 支持格式

| 格式 | 建议工具 |
|---|---|
| PDF | PyMuPDF / pdfplumber / Unstructured |
| Word | python-docx / Unstructured |
| Markdown | markdown-it / LangChain MarkdownTextSplitter |
| TXT | 直接读取 |
| HTML | BeautifulSoup / Trafilatura |
| Excel | pandas / openpyxl，转成结构化文本 |

---

## 13.2 切片策略

推荐：

```text
chunk_size: 300 - 800 tokens
chunk_overlap: 50 - 120 tokens
```

如果是论文、合同、财报，建议尽量保留结构：

```text
标题
章节
段落
表格
页码
```

切片示例：

```text
【文档标题】2026 AI 行业报告
【章节】3.2 行业风险
【页码】5

本项目可能面临数据合规风险。随着监管趋严……
```

这样 Embedding 效果会更好。

---

## 13.3 表格处理

表格不要直接丢弃。

可以转成自然语言：

```text
表格标题：风险等级表
行1：风险类型=数据泄露，等级=高，影响=重大
行2：风险类型=合规处罚，等级=中，影响=中等
```

或者转成 Markdown：

```markdown
| 风险类型 | 等级 | 影响 |
|---|---|---|
| 数据泄露 | 高 | 重大 |
| 合规处罚 | 中 | 中等 |
```

---

# 十四、多文档问答的关键设计

用户可能问：

```text
根据文档 A 和文档 B，说明两者观点是否一致？
```

这时需要重点利用 `doc_id` 过滤和跨文档证据对比。

---

## 14.1 指定文档过滤

如果用户选择：

```json
{
  "document_ids": ["doc_001", "doc_002"]
}
```

检索时必须限制：

```python
doc_id in ["doc_001", "doc_002"]
```

否则可能召回无关文档。

---

## 14.2 多文档证据标注

每条证据都应该带：

```text
doc_id
filename
page
section
chunk_id
```

最终答案中可以这样展示：

```text
根据《2026 AI 行业报告》第 5 页：
……

根据《合规指引》第 12 页：
……

两份文档在数据合规风险上的表述基本一致，但后者更强调跨境数据问题。
```

---

## 14.3 冲突检测

在证据分析 Prompt 中加入：

```text
如果不同文档之间存在矛盾，请明确指出：
1. 哪篇文档怎么说
2. 哪篇文档怎么说
3. 差异是什么
```

---

# 十五、避免无限循环的控制策略

多轮调研最大的问题是可能陷入循环。

必须加入限制。

---

## 15.1 最大轮次限制

```python
max_iterations = 5
```

超过后强制回答，并说明：

```text
基于当前已检索到的文档内容，只能得出以下结论……
```

---

## 15.2 查询去重

```python
if query in searched_queries:
    skip
```

避免同一个问题反复查。

---

## 15.3 新增证据检测

如果连续两轮：

```text
没有新增有效证据
没有新增 chunk_id
findings 没有变化
```

则停止调研。

---

## 15.4 分数阈值

如果检索结果最高分过低：

```text
score < threshold
```

说明文档中可能没有相关内容。

可以回答：

```text
当前文档中未找到足够证据。
```

---

## 15.5 Token 预算

每轮检索都会增加上下文，要控制：

```text
最多保留 Top N 条证据
每条证据最多 M 字
总上下文不超过模型限制
```

---

# 十六、检索优化建议

---

## 16.1 初筛多召回，后精排

建议：

```text
每个 query 召回 20 - 50 条
Rerank 后保留 8 - 12 条
```

如果不用 Rerank：

```text
每个 query 召回 8 - 15 条
```

---

## 16.2 召回相邻切片

当某个切片很有价值时，可以召回上下文：

```python
chunk_index - 1
chunk_index
chunk_index + 1
```

Qdrant 中可以通过 `chunk_index` 和 `doc_id` 过滤：

```python
Filter(
    must=[
        FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
        FieldCondition(key="chunk_index", range=Range(gte=index-1, lte=index+1))
    ]
)
```

这对长文档理解很有帮助。

---

## 16.3 混合检索

如果你希望关键词命中能力更强，可以在 Qdrant 中启用：

```text
向量检索 + 全文检索
```

思路：

```text
Dense Vector：语义相似
Sparse Vector / BM25：关键词匹配
RRF Fusion：融合结果
```

对于合同、法规、技术文档，混合检索通常比纯向量检索更稳。

---

# 十七、工程目录建议

```text
project/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── documents.py
│   │   ├── ask.py
│   │   └── sessions.py
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   └── exceptions.py
│   ├── services/
│   │   ├── document_service.py
│   │   ├── parser_service.py
│   │   ├── chunk_service.py
│   │   ├── embedding_service.py
│   │   ├── qdrant_service.py
│   │   ├── agent_service.py
│   │   └── llm_service.py
│   ├── agents/
│   │   ├── research_agent.py
│   │   ├── prompts.py
│   │   ├── state.py
│   │   └── tools.py
│   ├── models/
│   │   ├── document.py
│   │   ├── session.py
│   │   └── citation.py
│   └── db/
│       ├── postgres.py
│       └── redis.py
├── scripts/
│   └── init_qdrant.py
├── tests/
│   ├── test_parser.py
│   ├── test_qdrant.py
│   └── test_agent.py
└── requirements.txt
```

---

# 十八、推荐技术栈

| 模块 | 推荐 |
|---|---|
| Web 框架 | FastAPI |
| Agent 编排 | LangGraph / LangChain |
| 向量库 | Qdrant |
| Embedding | bge-m3 / OpenAI / Qwen Embedding |
| LLM | Qwen、DeepSeek、OpenAI、本地 vLLM |
| 文档解析 | Unstructured / PyMuPDF / python-docx |
| 会话存储 | PostgreSQL / Redis |
| 任务队列 | Celery / RQ / FastAPI BackgroundTasks |
| 流式输出 | SSE / WebSocket |
| 观测 | LangSmith / Phoenix / OpenTelemetry |

---

# 十九、最小可用版本 MVP

如果你想快速落地，第一版可以只做这些：

```text
1. 上传 PDF / Markdown / TXT
2. 文档解析
3. 固定长度切片
4. Embedding 入 Qdrant
5. 用户提问时指定 document_ids
6. Agent 最多调研 3 轮
7. 每轮生成 1 - 2 个查询
8. 每次检索 10 条
9. 最终回答带引用
```

不要一开始就做太复杂。

---

# 二十、推荐演进路线

---

## 阶段一：基础 RAG

```text
上传文档
切片入库
一次检索
生成答案
```

目标：跑通链路。

---

## 阶段二：多轮调研

```text
问题改写
多轮检索
证据累积
是否继续判断
```

目标：提升复杂问题回答质量。

---

## 阶段三：混合检索

```text
向量检索
全文检索
RRF 融合
Rerank
```

目标：提升关键词命中和复杂查询能力。

---

## 阶段四：文档结构增强

```text
章节识别
表格解析
图片转文本
目录提取
标题层级保留
```

目标：提升长文档理解。

---

## 阶段五：多智能体协作

可以进一步拆成：

```text
Planner Agent：拆解问题
Retriever Agent：负责检索
Analyzer Agent：分析证据
Critic Agent：检查证据是否充分
Writer Agent：生成最终答案
```

目标：处理更复杂的跨文档调研任务。

---

# 二十一、关键难点与解决方案

| 难点 | 解决方案 |
|---|---|
| 一次检索找不全 | 多轮调研、问题改写、子问题拆解 |
| 检索结果噪声大 | Rerank、分数阈值、证据筛选 |
| 多文档答案冲突 | 证据标注来源、冲突检测、分别陈述 |
| Agent 无限循环 | 最大轮次、查询去重、新增证据检测 |
| 长文档上下文丢失 | 相邻切片召回、章节摘要、文档级摘要 |
| 表格理解差 | 表格转 Markdown / 自然语言 |
| 引用不准 | 强制要求答案引用 `chunk_id` |
| LLM 编造 | 限制只能使用证据，要求低置信度时说明 |
| 多用户数据混乱 | `user_id` 强制过滤 |
| 指定文档范围失效 | `doc_id` 必须进入 Qdrant filter |

---

# 二十二、最终推荐架构

如果你要做一个生产级版本，我建议采用如下架构：

```text
FastAPI
  ├── /documents/upload        文档上传
  ├── /documents/{id}/status   文档解析状态
  ├── /ask                     智能问答
  └── /ask/stream              SSE 流式返回调研过程

Document Worker
  ├── 文件解析
  ├── 结构提取
  ├── 切片
  ├── Embedding
  └── 写入 Qdrant

Research Agent
  ├── PlanQueriesNode
  ├── RetrieveNode
  ├── AnalyzeEvidenceNode
  ├── DecideNode
  └── FinalAnswerNode

Qdrant
  ├── document_chunks collection
  ├── dense vector
  ├── optional sparse vector
  └── payload filters: user_id, doc_id, filename, page, section

PostgreSQL
  ├── users
  ├── documents
  ├── sessions
  ├── answers
  └── citations

Redis
  ├── task status
  ├── session cache
  └── rate limit
```

---

# 二十三、一句话总结

这个系统的核心不是“查一次就回答”，而是：

> **把文档检索变成一个可循环、可判断、可追踪的调研过程。**

推荐实现方式：

```text
FastAPI 负责接口和任务管理
Qdrant 负责向量存储和文档范围过滤
LangGraph 负责多轮调研状态机
LLM 负责问题拆解、证据分析、继续检索判断和最终回答
```

最小闭环可以概括为：

```text
用户提问
  ↓
生成查询
  ↓
Qdrant 检索
  ↓
提取证据
  ↓
判断是否充分
  ↓
不足则继续查
  ↓
充分则生成带引用的答案
```