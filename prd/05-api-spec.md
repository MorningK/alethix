# 05 · 接口规范（API Specification）

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v1.0 |
| 更新日期 | 2026-09-04 |
| 基础路径 | `/api/v1` |
| 协议 | HTTP/1.1 · REST + SSE |
| 上游文档 | [README](./README.md) · [01-prd.md](./01-prd.md) · [02-architecture.md](./02-architecture.md) |
| 关联文档 | [03-agent-design.md](./03-agent-design.md) · [04-data-model.md](./04-data-model.md) |

---

## 1. 通用约定

### 1.1 基础信息

| 项 | 约定 |
| --- | --- |
| 基础路径 | `/api/v1` |
| 请求编码 | `UTF-8` |
| 响应格式 | `application/json; charset=utf-8` |
| 流式格式 | `text/event-stream; charset=utf-8` |
| 时间格式 | RFC 3339，UTC，例：`2026-09-04T10:00:00Z` |
| ID 格式 | UUID v4 字符串（见 [04-data-model.md §2.1](./04-data-model.md#21-关于-id-的设计修正重要)） |
| OpenAPI | 由 FastAPI 自动生成，位于 `/docs` |

### 1.2 鉴权与用户标识

| 项 | 约定 |
| --- | --- |
| MVP | 无内置鉴权体系，由网关统一鉴权后注入 `X-User-Id` 请求头 |
| 请求头 | `X-User-Id: <uuid>`（**必填**） |
| 服务端行为 | 一律以 `X-User-Id` 为当前用户身份，**不信任** Body / Query 中的任何用户标识字段 |
| 越权处理 | 访问不属于当前用户的资源一律返回 `404`（不返回 `403`，避免资源存在性探测，NFR-3.2） |

### 1.3 分页

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `page` | int | 1 | 从 1 开始 |
| `page_size` | int | 20 | 取值范围 1 ~ 100 |

分页响应统一结构：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

### 1.4 幂等性

| 场景 | 机制 |
| --- | --- |
| 文档上传 | 服务端按 `user_id + content_hash` 去重，天然幂等（[API-2](#api-2-post-documentsupload)） |
| 问答请求 | 可选请求头 `Idempotency-Key: <uuid>`；重复请求返回首次结果，缓存 24h |

### 1.5 统一响应封装

**成功响应**直接返回业务对象（不做 `{code, data, message}` 包装），便于前端直接使用。

**错误响应**统一结构：

```json
{
  "error": {
    "code": "4001003",
    "message": "不支持的文件类型或文件超过大小限制",
    "details": {
      "allowed_extensions": ["pdf", "md", "txt"],
      "max_size_mb": 50
    },
    "trace_id": "9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34"
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `error.code` | 业务错误码，6 位数字，见 [§5](#5-错误码表) |
| `error.message` | 用户可读的中文描述，不含堆栈与内部路径（NFR-3.7） |
| `error.details` | 可选，结构化补充信息 |
| `error.trace_id` | 链路追踪 ID，便于定位日志 |

---

## 2. 核心数据结构

以下结构在多个接口中复用。

### 2.1 DocumentBrief（文档摘要）

```json
{
  "document_id": "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
  "filename": "2026_ai_report.pdf",
  "status": "ready",
  "source_format": "pdf",
  "file_size_bytes": 5242880,
  "chunk_count": 235,
  "page_count": 78,
  "created_at": "2026-09-04T10:00:00Z",
  "ready_at": "2026-09-04T10:01:12Z"
}
```

### 2.2 Citation（引用）

```json
{
  "document_id": "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
  "chunk_id": "b1e2d3c4-5f6a-7b8c-9d0e-1f2a3b4c5d6e",
  "filename": "2026_ai_report.pdf",
  "page": 5,
  "section": "3.2 行业风险",
  "quote": "本项目可能面临数据合规风险。随着监管趋严……",
  "score": 0.82
}
```

### 2.3 Iteration（迭代记录）

```json
{
  "iteration": 1,
  "queries": ["文档中提到的主要风险因素", "合规风险 数据安全 法律责任"],
  "retrieved_chunk_count": 18,
  "new_chunk_count": 18,
  "findings": [
    "文档第 3 页提到数据合规风险",
    "文档第 7 页提到供应链中断风险"
  ],
  "conflicts": [],
  "decision": "continue",
  "reason": "已覆盖部分风险，但缺少风险等级与应对措施的说明",
  "missing_information": "缺少风险等级划分与对应的缓解方案"
}
```

| 字段 | 说明 |
| --- | --- |
| `decision` | `continue` = 继续调研；`answer` = 判定充分并收尾 |
| `new_chunk_count` | 相对历史的新增切片数，为 0 时会计入 `no_new_evidence` 判定 |

---

## 3. 接口定义

### 接口总览

| ID | 方法 | 路径 | 说明 | 对应需求 |
| --- | --- | --- | --- | --- |
| [API-1](#api-1-post-sessions) | POST | `/sessions` | 创建会话 | FR-4 |
| [API-2](#api-2-post-documentsupload) | POST | `/documents/upload` | 上传文档 | FR-1 |
| [API-3](#api-3-get-documentsdocument_idstatus) | GET | `/documents/{document_id}/status` | 查询文档处理状态 | FR-2 |
| [API-4](#api-4-get-documents) | GET | `/documents` | 文档列表 | FR-3 |
| [API-5](#api-5-delete-documentsdocument_id) | DELETE | `/documents/{document_id}` | 删除文档 | FR-3 |
| [API-6](#api-6-post-ask) | POST | `/ask` | 同步智能问答 | FR-5 ~ FR-11 |
| [API-7](#api-7-post-askstream) | POST | `/ask/stream` | 流式智能问答（SSE） | FR-9 |
| [API-8](#api-8-get-sessionssession_idmessages) | GET | `/sessions/{session_id}/messages` | 会话历史 | FR-10 |

---

### API-1 POST /sessions

创建会话。

**请求**

```http
POST /api/v1/sessions
X-User-Id: 9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34
Content-Type: application/json
```

```json
{
  "title": "AI 行业报告研读",
  "default_document_ids": [
    "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d"
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 否 | 会话标题，默认取首个提问的前 20 字 |
| `default_document_ids` | string[] | 否 | 会话默认检索范围，最多 20 个；为空表示不限定 |

**响应** `201 Created`

```json
{
  "session_id": "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f",
  "title": "AI 行业报告研读",
  "default_document_ids": [
    "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d"
  ],
  "message_count": 0,
  "created_at": "2026-09-04T10:00:00Z"
}
```

**错误码**：`4004001`（参数校验失败）、`4010001`（未认证）

---

### API-2 POST /documents/upload

上传文档，异步处理。

**请求**

```http
POST /api/v1/documents/upload
X-User-Id: 9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | file | 是 | 文档文件 |
| `session_id` | string | 否 | 若传入，自动将该文档加入会话的默认检索范围 |

**响应** `202 Accepted`

```json
{
  "document_id": "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
  "filename": "2026_ai_report.pdf",
  "status": "uploaded",
  "deduplicated": false,
  "created_at": "2026-09-04T10:00:00Z"
}
```

**重复上传**（命中 `content_hash` 去重，AC-1.5）

```json
{
  "document_id": "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
  "filename": "2026_ai_report.pdf",
  "status": "ready",
  "deduplicated": true,
  "created_at": "2026-09-04T09:12:33Z"
}
```

| 约束 | 值 | 违反时错误码 |
| --- | --- | --- |
| 允许扩展名 | `pdf` / `docx` / `md` / `txt` / `html`（MVP 为 `pdf` / `md` / `txt`） | `4001003` |
| 魔数校验 | 必须与实际格式匹配，不信任扩展名 | `4001003` |
| 单文件大小 | ≤ 50 MB | `4001003` |
| 单用户文档数 | ≤ 500 | `4001005` |

**错误码**：`4001001`、`4001002`、`4001003`、`4001004`、`4001005`、`4002001`

---

### API-3 GET /documents/{document_id}/status

查询文档处理状态。前端建议 2 秒轮询一次。

**请求**

```http
GET /api/v1/documents/3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d/status
X-User-Id: 9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34
```

**响应** `200 OK`

```json
{
  "document_id": "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
  "filename": "2026_ai_report.pdf",
  "status": "ready",
  "chunk_count": 235,
  "page_count": 78,
  "updated_at": "2026-09-04T10:01:12Z",
  "error": null
}
```

**处理中**

```json
{
  "document_id": "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
  "filename": "2026_ai_report.pdf",
  "status": "embedding",
  "chunk_count": null,
  "page_count": null,
  "updated_at": "2026-09-04T10:00:58Z",
  "error": null
}
```

**失败**

```json
{
  "document_id": "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
  "filename": "2026_ai_report.pdf",
  "status": "failed",
  "chunk_count": null,
  "page_count": null,
  "updated_at": "2026-09-04T10:00:31Z",
  "error": {
    "code": "4001004",
    "message": "文档已损坏或为扫描件，未能提取到可检索的文本"
  }
}
```

**错误码**：`4010001`、`4041001`（文档不存在或不属于当前用户，返回 `404`）

---

### API-4 GET /documents

文档列表。

**请求**

```http
GET /api/v1/documents?page=1&page_size=20&status=ready
X-User-Id: 9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 否 | 按状态过滤，取值见 [状态枚举](./README.md#状态枚举速查) |
| `page` | int | 否 | 默认 1 |
| `page_size` | int | 否 | 默认 20，最大 100 |

**响应** `200 OK`

```json
{
  "items": [
    {
      "document_id": "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
      "filename": "2026_ai_report.pdf",
      "status": "ready",
      "source_format": "pdf",
      "file_size_bytes": 5242880,
      "chunk_count": 235,
      "page_count": 78,
      "created_at": "2026-09-04T10:00:00Z",
      "ready_at": "2026-09-04T10:01:12Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

按 `created_at` 倒序返回（AC-1.7）。

**错误码**：`4010001`

---

### API-5 DELETE /documents/{document_id}

删除文档。软删立即生效，物理清理异步执行。

**请求**

```http
DELETE /api/v1/documents/3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d
X-User-Id: 9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34
```

**响应** `202 Accepted`

```json
{
  "document_id": "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
  "status": "deleting",
  "message": "文档已进入删除队列，向量数据将在后台清理"
}
```

**约束**

| 约束 | 说明 | 错误码 |
| --- | --- | --- |
| 仅 `ready` / `failed` 状态可删除 | 处理中的文档需先取消任务 | `4091002` |
| 级联删除 | 同时删除 `chunks` / `citations` 与 Qdrant Point（AC-1.8） | — |

**错误码**：`4010001`、`4041001`、`4091002`

---

### API-6 POST /ask

同步智能问答。返回完整答案与调研轨迹。

**请求**

```http
POST /api/v1/ask
X-User-Id: 9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34
Content-Type: application/json
```

```json
{
  "session_id": "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f",
  "question": "这篇文档里提到的主要风险有哪些？",
  "document_ids": [
    "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d"
  ],
  "max_iterations": 3
}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `session_id` | string | 是 | — | 会话 ID |
| `question` | string | 是 | — | 问题，1 ~ 2000 字符 |
| `document_ids` | string[] | 否 | 会话默认值 | 检索范围；为空表示用户全部 `ready` 文档 |
| `max_iterations` | int | 否 | 3 | 最大调研轮次，1 ~ 10 |

**响应** `200 OK`

```json
{
  "agent_run_id": "c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f",
  "session_id": "7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f",
  "question": "这篇文档里提到的主要风险有哪些？",

  "answer": "根据文档内容，主要风险包括：\n\n1. **数据合规风险**（第 3 页）：随着监管趋严……\n2. **供应链中断风险**（第 7 页）：关键零部件依赖单一供应商……\n\n需注意：文档未对各项风险给出明确的等级划分。",
  "confidence": "medium",

  "stop_reason": "max_iterations_reached",
  "iteration_count": 3,
  "duration_ms": 18400,
  "token_used": 24310,

  "iterations": [
    {
      "iteration": 1,
      "queries": ["文档中提到的主要风险因素"],
      "retrieved_chunk_count": 10,
      "new_chunk_count": 10,
      "findings": ["文档第 3 页提到数据合规风险"],
      "conflicts": [],
      "decision": "continue",
      "reason": "仅覆盖部分风险，缺少风险等级说明",
      "missing_information": "缺少风险等级划分与应对措施"
    },
    {
      "iteration": 2,
      "queries": ["风险等级 高 中 低", "风险应对措施 缓解方案"],
      "retrieved_chunk_count": 14,
      "new_chunk_count": 9,
      "findings": ["文档第 7 页提到供应链中断风险"],
      "conflicts": [],
      "decision": "continue",
      "reason": "补充了风险类型，但未找到明确的等级划分",
      "missing_information": "文档中可能不存在显式的风险等级表"
    },
    {
      "iteration": 3,
      "queries": ["风险矩阵 风险登记表"],
      "retrieved_chunk_count": 8,
      "new_chunk_count": 0,
      "findings": [],
      "conflicts": [],
      "decision": "answer",
      "reason": "已达到最大轮次，且连续无新增证据，基于现有证据作答",
      "missing_information": "风险等级划分"
    }
  ],

  "citations": [
    {
      "document_id": "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
      "chunk_id": "b1e2d3c4-5f6a-7b8c-9d0e-1f2a3b4c5d6e",
      "filename": "2026_ai_report.pdf",
      "page": 3,
      "section": "3.2 行业风险",
      "quote": "本项目可能面临数据合规风险。随着监管趋严……",
      "score": 0.82
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 场景 |
| --- | --- | --- |
| `4003001` | 400 | `document_ids` 中存在不属于当前用户的文档（AC-2.2） |
| `4003002` | 400 | `document_ids` 中存在未完成处理的文档（AC-2.3） |
| `4003003` | 400 | 指定文档数超过 20 |
| `4003004` | 400 | `max_iterations` 超出 1 ~ 10 |
| `4003005` | 400 | `question` 为空或超过 2000 字符 |
| `4002001` | 429 | 触发限流 |
| `4044001` | 404 | 会话不存在 |
| `5003001` | 500 | 智能体执行失败（见 [03 §8.2](./03-agent-design.md#82-各节点的保守默认值)） |
| `5032001` | 503 | LLM / Embedding 服务不可用（NFR-2.5） |

---

### API-7 POST /ask/stream

流式智能问答，SSE 推送调研过程。

**请求**：与 [API-6](#api-6-post-ask) 完全相同。

**响应头**

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

完整事件契约见 [§4](#4-sse-事件契约)。

**错误码**：与 API-6 一致。注意：**业务校验失败在进入流之前返回**，不会以 SSE 形式返回；只有执行过程中的异常才推送 `error` 事件。

---

### API-8 GET /sessions/{session_id}/messages

拉取会话历史。

**请求**

```http
GET /api/v1/sessions/7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f/messages?page=1&page_size=20
X-User-Id: 9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34
```

**响应** `200 OK`

```json
{
  "items": [
    {
      "message_id": "1024",
      "role": "user",
      "content": "这篇文档里提到的主要风险有哪些？",
      "created_at": "2026-09-04T10:05:00Z",
      "agent_run_id": null
    },
    {
      "message_id": "1025",
      "role": "assistant",
      "content": "根据文档内容，主要风险包括：……",
      "created_at": "2026-09-04T10:05:18Z",
      "agent_run_id": "c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f",
      "confidence": "medium",
      "citations": [
        {
          "document_id": "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
          "chunk_id": "b1e2d3c4-5f6a-7b8c-9d0e-1f2a3b4c5d6e",
          "filename": "2026_ai_report.pdf",
          "page": 3,
          "section": "3.2 行业风险",
          "quote": "本项目可能面临数据合规风险。随着监管趋严……"
        }
      ]
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20
}
```

按时间**正序**返回（AC-3.4）。

**错误码**：`4010001`、`4044001`

---

## 4. SSE 事件契约

### 4.1 事件序列

```text
started → ( iteration → retrieved → reasoning ) * → final_answer
               异常时任意位置 → error
```

| 序号 | 事件 | 触发时机 | 是否必然出现 |
| --- | --- | --- | --- |
| 1 | `started` | 图启动后立即推送 | 是 |
| 2 | `iteration` | `plan_queries` 节点完成 | 每轮 1 次 |
| 3 | `retrieved` | `retrieve_documents` 节点完成 | 每轮 1 次（`no_new_queries` 时跳过） |
| 4 | `reasoning` | `decide_next_step` 节点完成 | 每轮 1 次 |
| 5 | `final_answer` | `final_answer` 节点完成 | 是 |
| — | `error` | 执行异常 | 异常时 |

### 4.2 事件定义

#### `started`

```text
id: 1
event: started
data: {"agent_run_id":"c5d6e7f8-...","session_id":"7d4e5f60-...","question":"这篇文档里提到的主要风险有哪些？","max_iterations":3}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `agent_run_id` | string | 本次调研运行 ID |
| `session_id` | string | 会话 ID |
| `question` | string | 原始问题 |
| `max_iterations` | int | 最大轮次 |

#### `iteration`

```text
id: 2
event: iteration
data: {"iteration":1,"queries":["文档中提到的主要风险因素"],"searched_query_count":1}
```

#### `retrieved`

```text
id: 3
event: retrieved
data: {"iteration":1,"retrieved_chunk_count":10,"new_chunk_count":10,"max_score":0.82}
```

| 字段 | 说明 |
| --- | --- |
| `new_chunk_count` | 相对历史的新增切片数；为 0 会计入 `no_new_evidence` 判定 |
| `max_score` | 本轮最高检索分；低于阈值将触发 `low_relevance` |

#### `reasoning`

```text
id: 4
event: reasoning
data: {"iteration":1,"decision":"continue","reason":"仅覆盖部分风险，缺少风险等级说明","missing_information":"缺少风险等级划分与应对措施","findings_count":1,"conflicts_count":0}
```

| 字段 | 说明 |
| --- | --- |
| `decision` | `continue` / `answer` |
| `findings_count` | 累计发现数（不推送全文，控制体积，AG-5.4） |

#### `final_answer`

```text
id: 9
event: final_answer
data: {"agent_run_id":"c5d6e7f8-...","answer":"根据文档内容，主要风险包括：……","confidence":"medium","stop_reason":"max_iterations_reached","iteration_count":3,"duration_ms":18400,"token_used":24310,"citations":[{"chunk_id":"b1e2d3c4-...","filename":"2026_ai_report.pdf","page":3,"section":"3.2 行业风险","quote":"本项目可能面临数据合规风险……"}]}
```

#### `error`

```text
id: 5
event: error
data: {"code":"5003001","message":"智能体执行失败，请稍后重试","trace_id":"9f2c1a8e-..."}
```

### 4.3 完整示例

```text
: ok

id: 1
event: started
data: {"agent_run_id":"c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f","session_id":"7d4e5f60-8a9b-4c1d-2e3f-4a5b6c7d8e9f","question":"这篇文档里提到的主要风险有哪些？","max_iterations":3}

id: 2
event: iteration
data: {"iteration":1,"queries":["文档中提到的主要风险因素"],"searched_query_count":1}

id: 3
event: retrieved
data: {"iteration":1,"retrieved_chunk_count":10,"new_chunk_count":10,"max_score":0.82}

id: 4
event: reasoning
data: {"iteration":1,"decision":"continue","reason":"仅覆盖部分风险，缺少风险等级说明","missing_information":"缺少风险等级划分与应对措施","findings_count":1,"conflicts_count":0}

id: 5
event: iteration
data: {"iteration":2,"queries":["风险等级 高 中 低","风险应对措施 缓解方案"],"searched_query_count":3}

id: 6
event: retrieved
data: {"iteration":2,"retrieved_chunk_count":14,"new_chunk_count":9,"max_score":0.77}

id: 7
event: reasoning
data: {"iteration":2,"decision":"answer","reason":"补充了风险类型，继续检索收益有限，基于现有证据作答","missing_information":"","findings_count":3,"conflicts_count":0}

id: 8
event: final_answer
data: {"agent_run_id":"c5d6e7f8-9a0b-4c1d-2e3f-4a5b6c7d8e9f","answer":"根据文档内容，主要风险包括：……","confidence":"medium","stop_reason":"sufficient","iteration_count":2,"duration_ms":15200,"token_used":19240,"citations":[{"chunk_id":"b1e2d3c4-5f6a-7b8c-9d0e-1f2a3b4c5d6e","filename":"2026_ai_report.pdf","page":3,"section":"3.2 行业风险","quote":"本项目可能面临数据合规风险……"}]}
```

### 4.4 传输约定

| 编号 | 约定 |
| --- | --- |
| SSE-1 | 每个事件携带单调递增的 `id`，客户端断线时通过 `Last-Event-ID` 请求头重连，服务端从该 ID 之后重放（最多保留最近 100 个事件） |
| SSE-2 | 心跳：每 15 秒发送一行注释 `: ping\n\n`，防止代理层与客户端超时断开 |
| SSE-3 | 首字节时间 ≤ 3 秒（NFR-1.5），`started` 事件在图启动后立即推送 |
| SSE-4 | 客户端断开时服务端需取消图的执行，避免 LLM 调用空耗（AG-5.3） |
| SSE-5 | 事件载荷**不包含**检索到的原文全文，仅包含统计与摘要（AG-5.4） |
| SSE-6 | 反向代理需禁用缓冲（`X-Accel-Buffering: no`），否则事件会被攒批 |
| SSE-7 | 事件顺序严格按节点完成顺序推送，不保证跨轮次的并发节点顺序 |

---

## 5. 错误码表

### 5.1 编码规则

```text
{HTTP 状态码(3位)}{业务模块(1位)}{序号(2位)}

业务模块：
  1 = 文档（document）
  2 = 通用 / 限流（common）
  3 = 问答 / 智能体（ask）
  4 = 会话（session）
  9 = 系统内部（internal）
```

### 5.2 错误码清单

| 错误码 | HTTP | 含义 | 可能原因 / 处理建议 |
| --- | --- | --- | --- |
| `4001001` | 400 | 文档相关请求参数校验失败 | 检查请求体字段 |
| `4001002` | 400 | 缺少必填字段 `file` | multipart 表单不完整 |
| `4001003` | 400 | 不支持的文件类型或超过大小限制 | 允许 `pdf`/`md`/`txt`，≤ 50 MB |
| `4001004` | 400 | 文档为空、已损坏或无可提取文本 | 扫描件 PDF 需先 OCR |
| `4001005` | 400 | 文档数量超出配额 | 单用户上限 500 |
| `4002001` | 429 | 请求频率超限 | 见 [§6](#6-限流与超时)，稍后重试 |
| `4003001` | 400 | `document_ids` 中存在不属于当前用户的文档 | 检查文档归属（AC-2.2） |
| `4003002` | 400 | `document_ids` 中存在未完成处理的文档 | 等待文档 `ready`（AC-2.3） |
| `4003003` | 400 | 指定文档数超过 20 | 缩小范围 |
| `4003004` | 400 | `max_iterations` 超出 1 ~ 10 | 调整取值 |
| `4003005` | 400 | `question` 为空或超过 2000 字符 | 缩短问题 |
| `4004001` | 400 | 会话参数校验失败 | 检查 `default_document_ids` |
| `4010001` | 401 | 未认证或 `X-User-Id` 缺失 | 由网关注入身份 |
| `4041001` | 404 | 文档不存在 | 也可能因越权而返回 `404`（NFR-3.2） |
| `4044001` | 404 | 会话不存在 | 同上 |
| `4091002` | 409 | 文档处于处理中，无法删除 | 等待至终态再删除 |
| `5003001` | 500 | 智能体执行失败 | 可重试；携带 `trace_id` 排查 |
| `5003002` | 500 | 答案生成失败 | 结构化输出降级链全部失败 |
| `5009001` | 500 | 内部服务错误 | 携带 `trace_id` 排查 |
| `5032001` | 503 | LLM / Embedding 服务不可用 | 稍后重试（NFR-2.5） |
| `5032002` | 503 | 向量库不可用 | 稍后重试 |

> **注意**：HTTP 状态码用于表达语义类别，业务错误码用于精确定位问题。客户端应优先依据 `error.code` 做分支处理。

---

## 6. 限流与超时

### 6.1 限流策略

基于 Redis 固定窗口计数，按 `user_id` 维度。

| 接口 | 限流规则 | 键 | 超限响应 |
| --- | --- | --- | --- |
| `POST /ask`、`POST /ask/stream` | 20 次 / 分钟 / 用户 | `rate:ask:{user_id}:{minute}` | `429` + `4002001` |
| `POST /documents/upload` | 10 次 / 分钟 / 用户 | `rate:upload:{user_id}:{minute}` | `429` + `4002001` |
| 其余查询接口 | 120 次 / 分钟 / 用户 | `rate:read:{user_id}:{minute}` | `429` + `4002001` |

响应头携带限流信息：

```http
X-RateLimit-Limit: 20
X-RateLimit-Remaining: 17
X-RateLimit-Reset: 1756972860
Retry-After: 42
```

### 6.2 超时策略

| 环节 | 超时 | 超限行为 |
| --- | --- | --- |
| 上传接口 | 30 s（仅落元数据） | 超时返回 `5009001` |
| 单次 LLM 调用 | 60 s（`LLM_TIMEOUT_SECONDS`） | 重试，最多 3 次 |
| 单次问答整体 | 120 s（`AGENT_TIMEOUT_SECONDS`） | 触发 `budget_exceeded` 并收尾作答（NFR-2.6） |
| SSE 连接空闲 | 无活动 300 s 断开 | 客户端可重连 |
| 客户端读取超时 | 建议 ≥ 150 s | — |

---

## 7. 接口与需求映射

| 接口 | 覆盖需求 | 验收标准 |
| --- | --- | --- |
| [API-1](#api-1-post-sessions) | FR-4 | — |
| [API-2](#api-2-post-documentsupload) | FR-1 | AC-1.1 ~ AC-1.5 |
| [API-3](#api-3-get-documentsdocument_idstatus) | FR-2 | AC-1.2、AC-1.6、AC-4.5 |
| [API-4](#api-4-get-documents) | FR-3 | AC-1.7 |
| [API-5](#api-5-delete-documentsdocument_id) | FR-3 | AC-1.8 |
| [API-6](#api-6-post-ask) | FR-5 ~ FR-11 | AC-2.1 ~ AC-2.10、AC-3.1 ~ AC-3.3、AC-4.3、AC-4.4、AC-4.6、AC-4.7 |
| [API-7](#api-7-post-askstream) | FR-9 | AC-4.1、AC-4.2 |
| [API-8](#api-8-get-sessionssession_idmessages) | FR-10 | AC-3.4 |
