# Alethix · 探赜

基于 **LangGraph + Qdrant + FastAPI** 的智能阅读检索解答智能体（Agentic / Iterative RAG）。

上传文档后，你可以基于一篇或多篇文档提问。智能体会先检索一次，再判断证据是否充分；**不足则自动生成新的检索查询继续追查**，直到形成结论，最终给出带引用、可核验的答案。

> 与普通 RAG「查一次就回答」不同，本系统把文档检索变成一个**可循环、可判断、可追踪**的调研过程。

```
普通 RAG：  问题 → 一次检索 → TopK → 生成答案

探  赜：    问题 → 生成查询 → 检索 → 分析证据 → 判断是否充分
                      ↑                              ↓
                      └────────── 不足则继续 ←───────┘
                                  充分则生成带引用的答案
```

---

## 快速开始

### 1. 前置条件

| 工具                | 版本要求               | 说明         |
| ------------------- | ---------------------- | ------------ |
| Python              | ≥ 3.11（实测 3.12.13） | 后端         |
| uv                  | ≥ 0.11（实测 0.11.25） | 后端依赖管理 |
| Node.js             | ≥ 22（实测 24.18.0）   | 前端与工具链 |
| Docker + Compose v2 | 实测 v2.32.4           | 中间件容器   |

### 2. 环境变量

```bash
cp .env.example .env
```

然后填写 `OPENAI_API_KEY`。使用本地 TEI 做 Embedding 时，请**只**改 `EMBEDDING_BASE_URL`，
不要动 `OPENAI_BASE_URL`——详见下方 [注意事项](#注意事项)。

### 3. 启动中间件

```bash
docker compose up -d          # Qdrant / PostgreSQL / Redis
docker compose ps             # 确认三个服务均为 healthy
```

可选（本地 Embedding，默认不启动）：

```bash
docker compose --profile local-emb up -d
```

### 4. 启动后端

```bash
uv sync                                        # 安装依赖
uv run python scripts/init_qdrant.py           # 初始化向量集合与索引
uv run uvicorn app.main:app --port 8000 --reload
```

验证：

```bash
curl -H "X-User-Id: <uuid>" http://127.0.0.1:8000/healthz
# {"status":"ok","app_env":"dev","components":{"postgres":"ok","redis":"ok","qdrant":"ok"}}
```

### 5. 启动前端

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

前端通过 Vite proxy 把 `/api` 转发到后端，开发期无需配置 CORS。

---

## 技术栈

### 后端

| 层次            | 选型                                                           |
| --------------- | -------------------------------------------------------------- |
| Web             | FastAPI + Uvicorn                                              |
| 编排            | LangGraph（五节点显式状态机）                                  |
| LLM / Embedding | OpenAI 兼容接口（可切 vLLM / DeepSeek / Qwen / TEI）           |
| 向量库          | Qdrant（`document_chunks`，命名向量 `dense`，1536 维，COSINE） |
| 关系库          | PostgreSQL（SQLAlchemy 异步 + Alembic）                        |
| 缓存            | Redis                                                          |
| 依赖管理        | uv + `pyproject.toml`                                          |

### 前端

| 层次   | 选型                                       |
| ------ | ------------------------------------------ |
| 框架   | React 19 + TypeScript 7                    |
| 构建   | Vite 8                                     |
| 组件库 | Ant Design 6                               |
| 样式   | Tailwind CSS 4（仅布局，已禁用 preflight） |
| 状态   | TanStack Query（服务端）+ Zustand（UI）    |
| SSE    | `@microsoft/fetch-event-source`            |

### 中间件

| 服务        | 端口        | 说明                                                        |
| ----------- | ----------- | ----------------------------------------------------------- |
| Qdrant      | 6333 / 6334 | REST + gRPC，Dashboard 在 `http://localhost:6333/dashboard` |
| PostgreSQL  | 5432        | 权威数据源                                                  |
| Redis       | 6379        | 任务状态、缓存、限流                                        |
| TEI（可选） | 8080        | 本地 Embedding，`--profile local-emb` 才启动                |

---

## 目录结构

```text
.
├── app/                    # 后端主包
│   ├── main.py             # FastAPI 入口：lifespan、CORS、全局异常、健康检查
│   ├── api/                # 路由：documents / sessions / ask
│   ├── core/               # config、logging、errors、security
│   ├── services/           # 业务服务（qdrant / llm / embedding / retrieval …）
│   ├── agents/             # LangGraph：state / nodes / routing / graph / prompts
│   ├── models/             # SQLAlchemy ORM
│   ├── schemas/            # Pydantic DTO
│   └── db/                 # postgres / redis
├── workers/                # 异步任务（入库、清理与对账）
├── migrations/             # Alembic
├── scripts/                # init_qdrant、eval_runner
├── tests/                  # 单元测试
├── web/                    # 前端工程
│   └── src/
│       ├── pages/          # 文档管理、问答调研
│       ├── components/     # 布局与公共组件
│       ├── api/            # axios 与 SSE 封装
│       ├── types/          # 接口类型定义
│       ├── hooks/          # 轮询、调研流、会话
│       ├── store/          # Zustand
│       └── utils/          # 错误码映射、格式化
├── prd/                    # 产品与技术文档（8 篇）
├── docker-compose.yml      # 开发中间件
├── pyproject.toml / uv.lock
└── package.json            # 仓库级工具链（oxlint / oxfmt / husky）
```

---

## 常用命令

### 后端

| 命令                                           | 说明           |
| ---------------------------------------------- | -------------- |
| `uv sync`                                      | 安装依赖       |
| `uv run uvicorn app.main:app --reload`         | 启动开发服务   |
| `uv run pytest`                                | 运行测试       |
| `uv run ruff check .` / `uv run ruff format .` | 检查 / 格式化  |
| `uv run python scripts/init_qdrant.py`         | 初始化向量集合 |

### 前端

| 命令                              | 说明                |
| --------------------------------- | ------------------- |
| `npm run dev`                     | 开发服务（5173）    |
| `npm run build`                   | 类型检查 + 生产构建 |
| `npm run typecheck`               | 仅类型检查          |
| `npm run lint` / `npm run format` | oxlint / oxfmt      |

### 仓库级（在根目录执行）

| 命令                                      | 说明                    |
| ----------------------------------------- | ----------------------- |
| `npm run lint`                            | 检查前端代码（oxlint）  |
| `npm run format` / `npm run format:check` | oxfmt 格式化 / 校验     |
| `npm run lint:py` / `npm run format:py`   | 后端 ruff 检查 / 格式化 |
| `npx lint-staged`                         | 手动执行暂存区检查      |

---

## 代码规范与 Git Hooks

提交前会通过 **husky + lint-staged** 自动检查**暂存文件**：

| 文件                                  | 执行的检查                         |
| ------------------------------------- | ---------------------------------- |
| `web/src/**/*.{ts,tsx}`               | `oxlint --fix` → `oxfmt`           |
| `web/src/**/*.css`                    | `oxfmt`                            |
| `*.{json,md,yml,yaml}`                | `oxfmt`                            |
| `{app,workers,scripts,tests}/**/*.py` | `ruff check --fix` → `ruff format` |

> 首次克隆后需先执行根目录的 `npm install`，它会通过 `prepare` 脚本自动安装 Git Hooks。

**为什么用 oxlint / oxfmt 而不是 ESLint / Prettier？**
`typescript-eslint` 的 peer 约束是 `typescript >=4.8.4 <6.1.0`，**不支持本项目使用的 TypeScript 7**。
oxlint 与 oxfmt 由 Rust 实现、原生解析 TS/TSX，无此限制，且语言支持覆盖 TS / CSS / JSON / YAML / Markdown。

**换行符**：仓库通过 `.gitattributes` 统一为 LF。Windows 下若发现大量文件显示为已修改，
请确认 `.gitattributes` 生效；建议将首次格式化的提交加入 `.git-blame-ignore-revs`。

---

## 健康检查

| 端点                 | 说明                                                               |
| -------------------- | ------------------------------------------------------------------ |
| `GET /healthz`       | 返回各中间件连通性明细，任一不可用仍返回 200（`status: degraded`） |
| `GET /api/v1/health` | 业务前缀下的简易探活                                               |
| `GET /docs`          | Swagger UI                                                         |

---

## 注意事项

### 1. LLM 与 Embedding 的端点必须分开配置

两者默认都走 `OPENAI_BASE_URL`，但**实际常来自不同服务**。若把 `OPENAI_BASE_URL` 指向 TEI，
大模型调用会全部失败——因为 TEI 只实现 `/v1/embeddings`，没有 `/v1/chat/completions`。

正确做法是只设置专用变量（留空时自动回退到通用值）：

```bash
EMBEDDING_BASE_URL=http://localhost:8080/v1   # 只改这个
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024                            # bge-m3 是 1024 维，非 1536
QDRANT_COLLECTION=document_chunks_bgem3       # 必须换一个集合，禁止与 1536 维混用
```

### 2. Qdrant 升级前必须确认存储兼容性

Qdrant 存储格式跨版本不保证兼容。`docker-compose.yml` 中固定为 `v1.12.x`（与 `qdrant-client`
的 `>=1.12,<1.14` 约束对齐）。**切勿直接改版本号后重建容器**，否则会因 segment 反序列化失败
导致启动崩溃。升级前请先备份或确认迁移路径。

### 3. 业务功能尚未实现

当前为工程骨架阶段，文档解析、切片、向量化、LangGraph 节点、完整前端页面均为**带契约注释的占位实现**。
各占位模块均标注了对应的需求编号与里程碑，可据此继续填充。

---

## 文档

完整的产品与技术文档位于 [`prd/`](./prd)，建议按编号顺序阅读：

| 编号 | 文档                                        | 内容                                  |
| ---- | ------------------------------------------- | ------------------------------------- |
| —    | [README](./prd/README.md)                   | 文档入口、术语表、编号体系            |
| 01   | [产品需求](./prd/01-prd.md)                 | 功能/非功能需求、验收标准、MVP 边界   |
| 02   | [总体架构](./prd/02-architecture.md)        | 分层、流程时序、技术选型与配置清单    |
| 03   | [智能体设计](./prd/03-agent-design.md)      | 状态机、五节点契约、终止策略、Prompt  |
| 04   | [数据模型](./prd/04-data-model.md)          | PostgreSQL DDL、Qdrant 设计、Redis 键 |
| 05   | [接口规范](./prd/05-api-spec.md)            | REST 接口、SSE 事件契约、错误码       |
| 06   | [路线与风险](./prd/06-roadmap-and-risks.md) | 演进路线、里程碑、风险登记            |
| 07   | [前端实现路线](./prd/07-frontend.md)        | 页面结构、组件划分、状态管理          |

---

## 开发路线

| 阶段 | 内容                                       | 状态      |
| ---- | ------------------------------------------ | --------- |
| M0   | 基础设施（中间件、配置体系）               | ✅ 已完成 |
| M1   | 文档入库（解析、切片、向量化）             | ⬜ 待实现 |
| M2   | 基础问答（单次检索、带引用答案）           | ⬜ 待实现 |
| M3   | **多轮调研**（LangGraph 五节点、终止策略） | ⬜ 待实现 |
| M4   | 流式与会话（SSE、历史、追问）              | ⬜ 待实现 |
| M5   | 质量与观测（评测集、指标、对账）           | ⬜ 待实现 |
| M6   | 生产就绪（限流、部署、压测）               | ⬜ 待实现 |

前端对应 F1~F5 里程碑，详见 [prd/07-frontend.md](./prd/07-frontend.md#11-里程碑与工期估算)。

---

## 许可

内部项目，暂未开放授权。
