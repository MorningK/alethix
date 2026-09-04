# 探赜（Alethix）· 文档集

> **Alethix（探赜）** —— 一个基于 LangGraph + Qdrant + FastAPI 的 **Agentic / Iterative RAG（智能调研式检索增强问答）** 系统。

本文档集由项目根目录下的 [`draft.md`](../draft.md) 初步草稿细化而来，是该项目**唯一的产品与技术事实来源**，用于指导后续研发、测试与验收。

---

## 一、一句话定位

> 把「文档检索」变成一个**可循环、可判断、可追踪的调研过程**，而不是「查一次就回答」。

用户上传一篇或多篇文档后，可以基于这些文档提问。智能体会先检索一次，分析已获得的证据，判断证据是否足以回答问题；**不足则自动生成新的检索查询继续追查**，直到证据充分或触发终止条件，最终给出**带引用来源、可核验**的答案。

### 与普通 RAG 的本质差异

| 维度 | 普通 RAG | 本系统（Agentic RAG） |
| --- | --- | --- |
| 检索次数 | 固定 1 次 | 动态 1 ~ N 次，由模型判断 |
| 查询来源 | 用户原始问题（可选一次改写） | 每轮基于「已有发现 + 信息缺口」重新规划 |
| 证据累积 | 无，单轮 TopK 即上下文 | 跨轮累积 `findings`，过滤重复 `chunk_id` |
| 充分性判断 | 无 | 有，独立决策节点输出 `is_sufficient` 与 `missing_information` |
| 循环风险 | 不存在 | 存在，需五重终止策略兜底 |
| 过程可见性 | 只给答案 | 每轮查询、命中数、决策、理由全程可追踪（SSE 实时推送） |
| 成本控制 | 稳定 | 需 Token 预算与轮次上限约束 |

---

## 二、文档导航

建议按下表顺序阅读。每篇文档均可独立阅读，但也通过编号体系（`FR-x` / `NFR-x` / `API-x` / `DM-x`）与其他文档交叉引用。

| 序号 | 文档 | 内容 | 主要读者 |
| --- | --- | --- | --- |
| 0 | **README.md**（本文） | 文档集入口、术语表、编号体系、版本记录 | 全体 |
| 1 | [01-prd.md](./01-prd.md) | **产品需求文档**：定位、用户故事、功能需求（FR）、非功能需求（NFR）、MVP 边界、验收标准 | 产品 / 研发 / 测试 |
| 2 | [02-architecture.md](./02-architecture.md) | **总体技术架构**：分层、两条主流程时序、技术选型与权衡、部署视图、配置清单、工程目录 | 研发 / 架构 |
| 3 | [03-agent-design.md](./03-agent-design.md) | **LangGraph 智能体设计**（技术核心）：状态定义、五节点契约、条件边、终止策略、四套 Prompt 规范 | 研发 |
| 4 | [04-data-model.md](./04-data-model.md) | **数据模型**：PostgreSQL DDL、Qdrant Collection 与 Payload、Redis 键设计、一致性策略 | 研发 / DBA |
| 5 | [05-api-spec.md](./05-api-spec.md) | **接口规范**：REST 接口、SSE 事件契约、统一错误码、限流策略 | 前端 / 研发 |
| 6 | [06-roadmap-and-risks.md](./06-roadmap-and-risks.md) | **演进路线与质量保障**：五阶段路线、里程碑、风险登记表、测试与观测方案 | 全体 |

### 依赖关系

```text
01-prd.md  （定义「做什么」）
    ↓
02-architecture.md  （定义「用什么做、怎么分层」）
    ↓
03-agent-design.md ──┐
04-data-model.md   ──┼──（三者平级，共同细化架构）
05-api-spec.md     ──┘
    ↓
06-roadmap-and-risks.md  （定义「分几步做、有什么风险」）
```

---

## 三、全局术语表（Ubiquitous Language）

本文档集全局固定使用以下术语。**任何文档中不得使用同义词替代**，实现代码中的命名也应与此保持一致。

| 术语 | 中文 | 定义 | 对应 ID |
| --- | --- | --- | --- |
| `document` | 文档 | 用户上传的一个原始文件及其解析产物，是检索范围的最小授权单元 | `DM-2` |
| `chunk` | 切片 | 文档经切片后的一个文本片段，是向量检索与引用的最小单位 | `DM-3` |
| `session` | 会话 | 用户围绕一组文档进行连续问答的上下文容器 | `DM-4` |
| `message` | 消息 | 会话中的一条记录，可以是提问（question）或回答（answer） | `DM-5` |
| `agent_run` | 调研运行 | 一次提问触发的完整智能体执行过程，包含若干轮迭代与一个最终答案 | `DM-6` |
| `iteration` | 迭代轮次 | `agent_run` 中的一轮「规划 → 检索 → 分析 → 决策」循环 | `DM-7` |
| `finding` | 发现 | 智能体从检索片段中提取出的一条与问题相关的事实陈述，跨轮累积 | — |
| `citation` | 引用 | 答案中引用到的具体 `chunk` 及其原文片段，支持回跳核对 | `DM-9` |
| `query` | 检索查询 | 智能体为检索而生成的一句查询语句（非用户原始问题） | — |
| `evidence` | 证据 | 支撑答案的 `finding` 与 `citation` 的集合 | — |

### 状态枚举速查

**文档处理状态**（`documents.status`）

| 值 | 含义 | 是否终态 |
| --- | --- | --- |
| `uploaded` | 已上传，等待处理 | 否 |
| `parsing` | 解析中 | 否 |
| `chunking` | 切片中 | 否 |
| `embedding` | 向量化中 | 否 |
| `ready` | 可检索 | **是** |
| `failed` | 失败 | **是** |

**调研终止原因**（`agent_runs.stop_reason`）与完整终止策略见 [03-agent-design.md](./03-agent-design.md#5-终止策略与-stop_reason)。

| 值 | 含义 |
| --- | --- |
| `sufficient` | 模型判定证据充分，正常收尾 |
| `max_iterations_reached` | 达到最大轮次上限，强制作答 |
| `no_new_queries` | 去重后无新查询可检索 |
| `no_new_evidence` | 连续轮次无新增有效证据 |
| `low_relevance` | 检索分数低于阈值，判定文档无相关内容 |
| `budget_exceeded` | Token 预算或总耗时超限 |
| `internal_error` | 执行异常，兜底收尾 |

---

## 四、编号体系

所有需求、接口、数据实体都有稳定 ID，**跨文档引用时必须使用 ID 而非描述**，以保证可追溯。

| 前缀 | 含义 | 定义位置 |
| --- | --- | --- |
| `FR-x.y` | 功能需求（Functional Requirement） | [01-prd.md](./01-prd.md) |
| `NFR-x.y` | 非功能需求（Non-Functional Requirement） | [01-prd.md](./01-prd.md) |
| `API-x` | 对外接口 | [05-api-spec.md](./05-api-spec.md) |
| `DM-x` | 数据实体 | [04-data-model.md](./04-data-model.md) |
| `NODE-x` | LangGraph 状态机节点 | [03-agent-design.md](./03-agent-design.md) |
| `AG-x.y` | 智能体设计约束 | [03-agent-design.md](./03-agent-design.md) |
| `RSK-x` | 风险项 | [06-roadmap-and-risks.md](./06-roadmap-and-risks.md) |

技术方案章节中需反向标注「本设计对应 `FR-x.y`」，验收标准据此逐条对照。

---

## 五、已锁定的技术选型

以下选型为本项目**已确认决策**，文档中不再讨论替代方案（替代方案的权衡记录在 [02-architecture.md](./02-architecture.md)）。

| 层次 | 选型 | 关键参数 |
| --- | --- | --- |
| Web 框架 | FastAPI（Python 3.11+，全异步） | — |
| Agent 编排 | **LangGraph** Graph API | 五节点显式状态机 |
| LLM 接入 | OpenAI 兼容接口，`with_structured_output` | LLM 与 Embedding 端点可独立配置：`LLM_BASE_URL` / `EMBEDDING_BASE_URL`，留空回退 `OPENAI_BASE_URL` |
| Embedding | `text-embedding-3-small` | **1536 维**，COSINE |
| 向量库 | Qdrant | Collection `document_chunks`，命名向量 `dense` |
| 关系库 | PostgreSQL 15+ | SQLAlchemy 2.x + Alembic |
| 缓存 / 任务状态 | Redis 7 | 异步 worker 用 Celery / RQ / ARQ |
| 流式输出 | SSE（`text/event-stream`） | — |

---

## 六、版本记录

| 版本 | 日期 | 说明 | 作者 |
| --- | --- | --- | --- |
| v0.1（草稿） | 2026-09-04 | 初步方案梳理，见 [`draft.md`](../draft.md) | — |
| v1.0 | 2026-09-04 | 基于草稿细化产出完整 PRD 与技术设计文档集（本版） | — |

### 变更原则

- 需求变更需同步更新 `01-prd.md` 的 `FR` / `NFR` 编号，并回溯检查 `05-api-spec.md` 与 `06-roadmap-and-risks.md` 的映射表。
- 接口变更需同步 `05-api-spec.md` 与 `04-data-model.md`，并保证 `API-x` 编号稳定（废弃编号不复用）。
- 数据实体变更需通过 Alembic 迁移，并在 `04-data-model.md` 中记录迁移影响面。
