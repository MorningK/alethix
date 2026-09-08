"""FastAPI 应用入口。

负责：生命周期管理、CORS、trace_id 中间件、全局异常处理、路由注册、健康检查。
接口契约见 prd/05-api-spec.md；基础路径 /api/v1。
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import ERR_INTERNAL, ApiError, error_response
from app.core.logging import get_logger, safe_extra, setup_logging, trace_id_var, user_id_var
from app.db import postgres, redis
from app.services import qdrant_service

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时建立连接，关闭时释放资源。"""
    settings = get_settings()
    setup_logging(settings)

    logger.info(
        "应用启动",
        extra=safe_extra(
            app_env=settings.app_env,
            llm_base_url=settings.resolved_llm_base_url,
            embedding_base_url=settings.resolved_embedding_base_url,
        ),
    )

    # 初始化各中间件连接；任一失败不影响启动，由健康检查暴露
    postgres.init_postgres(settings)
    redis.init_redis(settings.redis_url)
    qdrant_service.init_qdrant(settings)

    try:
        created = qdrant_service.ensure_collection(settings)
    except Exception as exc:  # noqa: BLE001
        # 仅包裹初始化本身；成功日志放在 else 中，避免日志异常被误报为初始化失败
        logger.error("Qdrant collection 初始化失败：%s", exc, exc_info=exc)
    else:
        logger.info(
            "Qdrant collection 就绪",
            extra=safe_extra(
                collection=settings.qdrant_collection,
                collection_created=created,
            ),
        )

    yield

    await postgres.close_postgres()
    await redis.close_redis()
    qdrant_service.close_qdrant()
    logger.info("应用已关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Alethix（探赜）",
        description="基于 LangGraph + Qdrant + FastAPI 的智能阅读检索解答智能体",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # CORS：生产环境前后端可能不同域，此处作为兜底；开发期走 Vite proxy
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
    )

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
        token_t = trace_id_var.set(trace_id)
        token_u = user_id_var.set(request.headers.get("X-User-Id"))
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "请求完成",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            trace_id_var.reset(token_t)
            user_id_var.reset(token_u)
        response.headers["X-Trace-Id"] = trace_id
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=error_response(
                code=exc.code,
                message=exc.message,
                details=exc.details,
                trace_id=trace_id_var.get(),
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("未处理异常：%s", exc, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_response(
                code=ERR_INTERNAL,
                message="内部服务错误",
                trace_id=trace_id_var.get(),
            ),
        )

    register_routers(app)
    register_health(app)
    return app


def register_routers(app: FastAPI) -> None:
    """注册业务路由。各模块当前为占位实现，随里程碑填充。"""
    from app.api import ask, documents, sessions

    api_prefix = "/api/v1"
    app.include_router(sessions.router, prefix=api_prefix)
    app.include_router(documents.router, prefix=api_prefix)
    app.include_router(ask.router, prefix=api_prefix)


def register_health(app: FastAPI) -> None:
    """健康检查：任一组件不可用时仍返回 200，通过 components 明细暴露。"""

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, Any]:
        pg_ok = await postgres.check_postgres()
        redis_ok = await redis.check_redis()
        qdrant_ok = qdrant_service.check_qdrant()

        ok = pg_ok and redis_ok and qdrant_ok
        return {
            "status": "ok" if ok else "degraded",
            "app_env": get_settings().app_env,
            "components": {
                "postgres": "ok" if pg_ok else "error",
                "redis": "ok" if redis_ok else "error",
                "qdrant": "ok" if qdrant_ok else "error",
            },
        }

    @app.get("/api/v1/health", tags=["ops"])
    async def health() -> dict[str, Any]:
        return {"status": "ok", "service": "alethix"}


app = create_app()
