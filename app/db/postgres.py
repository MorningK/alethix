"""PostgreSQL 异步连接。

SQLAlchemy 2.x 异步引擎 + sessionmaker，由 lifespan 统一管理生命周期。
建表交给 Alembic，启动时不自动建表。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_postgres(settings: Settings) -> None:
    """创建异步引擎与会话工厂。在应用启动时调用一次。"""
    global _engine, _session_factory

    is_test = settings.app_env == "test"

    _engine = create_async_engine(
        settings.postgres_dsn,
        echo=False,
        pool_pre_ping=True,
        # 测试环境使用 NullPool，避免连接复用影响用例隔离
        poolclass=NullPool if is_test else None,
        pool_size=None if is_test else settings.postgres_pool_size,
        max_overflow=None if is_test else 10,
        json_serializer=lambda obj: obj,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def close_postgres() -> None:
    """释放引擎连接。在应用关闭时调用。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("PostgreSQL 未初始化，请先调用 init_postgres()")
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖项：为每个请求提供一个数据库会话。"""
    if _session_factory is None:
        raise RuntimeError("PostgreSQL 未初始化，请先调用 init_postgres()")

    async with _session_factory() as session:
        yield session


async def check_postgres() -> bool:
    """连通性探测，用于健康检查。失败返回 False 而不抛异常。"""
    if _engine is None:
        return False
    try:
        from sqlalchemy import text

        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def engine_state() -> dict[str, Any]:
    """引擎状态快照，供健康检查与排障使用。"""
    if _engine is None:
        return {"initialized": False}
    pool = _engine.pool
    return {
        "initialized": True,
        "pool_size": getattr(pool, "size", None) and pool.size(),
        "checked_out": getattr(pool, "checkedout", None) and pool.checkedout(),
    }
