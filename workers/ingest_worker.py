"""文档入库 worker。

消费 Redis 队列中的两类任务：
    queue:ingest → ingest_document（状态机 + 失败回滚）
    queue:purge  → purge_document（软删文档的物理清理）

可靠性设计：
    - doc:lock:{document_id} 幂等锁，避免并发 / 重启后重复入库
    - 指数退避有限重试（ingest_max_retries），仅对 5xx / 瞬时错误重试
    - 4xx 业务错误（如扫描件 4001004）不重试，直接以 failed 终态结束
    - SIGINT / SIGTERM 优雅退出（当前任务处理完后停止）

运行：
    uv run python -m workers.ingest_worker
"""

from __future__ import annotations

import asyncio
import signal

from app.core.config import Settings, get_settings
from app.core.errors import ERR_INTERNAL, ApiError
from app.core.logging import get_logger, safe_extra, setup_logging
from app.db import postgres
from app.db import redis as redis_db
from app.services import qdrant_service
from app.services.ingestion_service import ingest_document, purge_document

logger = get_logger(__name__)

_QUEUES = (redis_db.key_ingest_queue(), redis_db.key_purge_queue())
_LOCK_TTL_SECONDS = 600
_MAX_BACKOFF_SECONDS = 30


class IngestWorker:
    """队列消费者主循环。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._stopping = False

    def init_clients(self) -> None:
        """初始化中间件连接（幂等，可重复调用）。"""
        postgres.init_postgres(self._settings)
        redis_db.init_redis(self._settings.redis_url)
        qdrant_service.init_qdrant(self._settings)

    async def run(self) -> None:
        setup_logging(self._settings)
        # 入口（python -m workers）不会预先初始化中间件连接，必须在此处初始化
        self.init_clients()
        logger.info("ingest worker 启动", extra=safe_extra(queues=list(_QUEUES)))
        try:
            while not self._stopping:
                try:
                    task = await redis_db.pop_task(_QUEUES, timeout=5)
                except Exception as exc:  # noqa: BLE001  # Redis 抖动不致死 worker
                    logger.warning("队列弹出失败，1s 后重试：%s", exc)
                    await asyncio.sleep(1)
                    continue
                if task is None:
                    continue
                queue_name, document_id = task
                await self._handle(queue_name, document_id)
        finally:
            await self._shutdown()
        logger.info("ingest worker 已退出")

    def request_stop(self) -> None:
        self._stopping = True

    # ---------------- 内部实现 ----------------

    async def _handle(self, queue_name: str, document_id: str) -> None:
        if queue_name == redis_db.key_purge_queue():
            await self._run_purge(document_id)
            return
        await self._run_ingest(document_id)

    async def _run_ingest(self, document_id: str) -> None:
        if not await redis_db.acquire_doc_lock(document_id, _LOCK_TTL_SECONDS):
            logger.info("文档正在处理中，跳过重复任务", extra=safe_extra(document_id=document_id))
            return
        try:
            await ingest_document(document_id, settings=self._settings)
            await redis_db.clear_retry_count(document_id)
        except ApiError as exc:
            await self._handle_ingest_failure(document_id, exc)
        except Exception as exc:  # noqa: BLE001
            await self._handle_ingest_failure(
                document_id, ApiError(ERR_INTERNAL, str(exc), status=500)
            )
        finally:
            await redis_db.release_doc_lock(document_id)

    async def _handle_ingest_failure(self, document_id: str, exc: ApiError) -> None:
        """4xx 不重试；5xx / 瞬时错误指数退避重投，超过上限放弃。"""
        if exc.status < 500:
            logger.warning(
                "文档入库失败（业务错误，不重试）",
                extra=safe_extra(document_id=document_id, error_code=exc.code),
            )
            return
        await self._requeue_with_backoff(document_id, redis_db.key_ingest_queue())

    async def _run_purge(self, document_id: str) -> None:
        if not await redis_db.acquire_doc_lock(document_id, _LOCK_TTL_SECONDS):
            logger.info(
                "文档清理正在进行中，跳过重复任务", extra=safe_extra(document_id=document_id)
            )
            return
        try:
            await purge_document(document_id, settings=self._settings)
            await redis_db.clear_retry_count(document_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("文档物理清理失败：%s", exc, extra=safe_extra(document_id=document_id))
            await self._requeue_with_backoff(document_id, redis_db.key_purge_queue())
        finally:
            await redis_db.release_doc_lock(document_id)

    async def _requeue_with_backoff(self, document_id: str, queue_key: str) -> bool:
        """指数退避重投任务；超过 ingest_max_retries 记错误并放弃（需对账补偿）。"""
        retry = await redis_db.next_retry_count(document_id)
        if retry > self._settings.ingest_max_retries:
            logger.error(
                "任务重试次数耗尽，放弃该文档",
                extra=safe_extra(document_id=document_id, retry=retry),
            )
            return False
        backoff = min(2**retry, _MAX_BACKOFF_SECONDS)
        logger.info(
            "任务将重试（第 %d 次，%ds 后）",
            retry,
            backoff,
            extra=safe_extra(document_id=document_id),
        )
        await asyncio.sleep(backoff)
        await redis_db.rpush(queue_key, document_id)
        return True

    async def _shutdown(self) -> None:
        try:
            await redis_db.close_redis()
        except Exception:  # noqa: BLE001
            pass
        try:
            await postgres.close_postgres()
        except Exception:  # noqa: BLE001
            pass
        qdrant_service.close_qdrant()


async def _amain() -> None:
    worker = IngestWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except (NotImplementedError, RuntimeError):  # Windows 无 add_signal_handler
            signal.signal(sig, lambda *_: worker.request_stop())
    await worker.run()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
