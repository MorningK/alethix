"""结构化日志。

输出 JSON 格式，携带 trace_id / user_id / agent_run_id 等上下文（NFR-4.2）。
禁止记录文档正文与密钥（NFR-3.7）。
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings

# 请求级上下文，由中间件写入
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


# logging.LogRecord 的内置属性。若出现在 extra 中，logging 会抛
# KeyError("Attempt to overwrite 'xxx' in LogRecord")，导致该条日志无法输出。
# 曾因 extra={"created": ...} 触发过，故此处集中声明并做防护。
LOG_RECORD_RESERVED: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def safe_extra(**fields: Any) -> dict[str, Any]:
    """构造可安全传给 extra 的字典：与 LogRecord 保留属性冲突的键会被重命名。

    例：safe_extra(created=True) -> {"field_created": True}
    """
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        safe[f"field_{key}" if key in LOG_RECORD_RESERVED else key] = value
    return safe


class JsonFormatter(logging.Formatter):
    """将日志记录渲染为单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        trace_id = trace_id_var.get()
        if trace_id:
            payload["trace_id"] = trace_id

        user_id = user_id_var.get()
        if user_id:
            payload["user_id"] = user_id

        # 透传 extra 字段
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = "%(levelname)-8s %(name)s %(message)s"
        self._style = logging.PercentStyle(base)
        result = super().format(record)
        trace_id = trace_id_var.get()
        if trace_id:
            result = f"[trace={trace_id}] {result}"
        return result


def setup_logging(settings: Settings) -> None:
    """配置根日志器。幂等，可重复调用。"""
    root = logging.getLogger()
    root.setLevel(settings.log_level)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_format == "json" else TextFormatter())
    root.addHandler(handler)

    # 降低第三方库噪音
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
