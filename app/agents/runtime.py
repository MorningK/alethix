"""智能体运行期依赖与检查点生命周期。

运行期依赖通过 ``RunnableConfig['configurable']['agent_deps']`` 注入，
不写入 ``AgentState``，从而保持状态可序列化并便于测试替身。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import Settings, get_settings
from app.schemas.document import Citation as CitationDTO
from app.services.retrieval_service import RetrievedChunk


@dataclass(frozen=True)
class AgentDeps:
    """节点使用的外部能力集合。"""

    settings: Settings
    call_structured: Callable[..., Awaitable[Any]]
    retrieve: Callable[..., Awaitable[list[RetrievedChunk]]]
    build_citations: Callable[..., tuple[list[CitationDTO], int]]


def build_agent_deps(settings: Settings | None = None) -> AgentDeps:
    """构造生产环境运行期依赖。"""
    from app.services import citation_service, retrieval_service
    from app.services.llm_service import invoke_structured

    s = settings or get_settings()
    return AgentDeps(
        settings=s,
        call_structured=invoke_structured,
        retrieve=retrieval_service.search,
        build_citations=citation_service.build_citations,
    )


def get_agent_deps(config: RunnableConfig) -> AgentDeps:
    """从 LangGraph 配置中取出运行期依赖。"""
    deps = (config.get("configurable") or {}).get("agent_deps")
    if not isinstance(deps, AgentDeps):
        raise RuntimeError("缺少 agent_deps，请先通过 agent_service 构建运行配置")
    return deps


def build_run_config(
    agent_run_id: str,
    deps: AgentDeps,
    filename_map: dict[str, str],
    *,
    max_iterations: int | None = None,
) -> RunnableConfig:
    """构造 thread_id = agent_run_id 的图运行配置。"""
    rounds = max_iterations or deps.settings.agent_max_iterations
    return {
        "configurable": {
            "thread_id": agent_run_id,
            "agent_deps": deps,
            "metrics": {
                "fallback_count": 0,
                "llm_call_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "citation_filtered_count": 0,
                "hits_by_id": {},
                "filename_map": filename_map,
                "last_new_chunk_count": 0,
                "last_findings": [],
                "last_conflicts": [],
                "history_findings": [],
            },
        },
        "recursion_limit": rounds * 4 + 4,
    }


def get_metrics(config: RunnableConfig) -> dict[str, Any]:
    """取出本次运行的成本与跨轮辅助数据。"""
    metrics = (config.get("configurable") or {}).get("metrics")
    if not isinstance(metrics, dict):
        raise RuntimeError("缺少运行期 metrics，请先通过 agent_service 构建运行配置")
    return metrics


_checkpointer_cm: AbstractAsyncContextManager[Any] | None = None
_checkpointer: Any | None = None


def _psycopg_dsn(settings: Settings) -> str:
    """把 SQLAlchemy 异步 DSN 转成 psycopg 可识别的连接串。"""
    return settings.postgres_dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


async def init_checkpointer(settings: Settings | None = None) -> Any:
    """初始化图检查点；测试环境使用内存实现。"""
    global _checkpointer_cm, _checkpointer

    s = settings or get_settings()
    if s.app_env == "test":
        _checkpointer_cm = None
        _checkpointer = InMemorySaver()
        return _checkpointer

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    # 表结构由 Alembic 迁移 0003 管理；此处不调用 setup()。
    cm = AsyncPostgresSaver.from_conn_string(_psycopg_dsn(s))
    _checkpointer = await cm.__aenter__()
    _checkpointer_cm = cm
    return _checkpointer


async def close_checkpointer() -> None:
    """释放检查点连接。"""
    global _checkpointer_cm, _checkpointer

    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)
    _checkpointer_cm = None
    _checkpointer = None


def get_checkpointer() -> Any:
    """获取已初始化的检查点；未初始化时抛错，避免静默丢失状态。"""
    if _checkpointer is None:
        raise RuntimeError("Checkpointer 未初始化，请先调用 init_checkpointer()")
    return _checkpointer


STOP_REASON_GUIDANCE: dict[str, str] = {
    "sufficient": "注意：证据充分，请正常陈述结论并附引用。",
    "max_iterations_reached": "注意：检索已达轮次上限，请在答案开头说明结论可能不完整。",
    "no_new_queries": "注意：已尝试的检索方向均已覆盖，请基于已获得证据给出结论。",
    "no_new_evidence": "注意：继续检索未获得新的有效信息，请据此给出结论。",
    "low_relevance": (
        "注意：未找到足够证据，请直接说明在所选文档中未找到足够证据，"
        "并列出最相关的内容供用户判断，不要强行作答。"
    ),
    "budget_exceeded": "注意：因检索规模受限，以下结论可能不完整。",
    "internal_error": "注意：执行过程中发生异常，请说明当前证据不足以形成可靠结论。",
}


def stop_reason_guidance(stop_reason: str | None) -> str:
    """把终止原因映射为终答 Prompt 注入文案。"""
    return STOP_REASON_GUIDANCE.get(stop_reason or "", "")
