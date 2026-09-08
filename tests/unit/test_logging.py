"""结构化日志测试。

重点：extra 中若含 LogRecord 保留属性（如 created、name、module），
logging 会抛 KeyError 导致整条日志丢失，且异常可能被上层误判为业务失败。
"""

from __future__ import annotations

import logging

from app.core.logging import LOG_RECORD_RESERVED, JsonFormatter, safe_extra


def test_safe_extra_renames_reserved_keys():
    """保留属性必须被重命名，避免覆盖 LogRecord。"""
    result = safe_extra(created=True, collection="document_chunks")

    assert "created" not in result
    assert result["field_created"] is True
    # 非保留键保持原样
    assert result["collection"] == "document_chunks"


def test_safe_extra_keeps_normal_keys():
    result = safe_extra(app_env="dev", duration_ms=12)
    assert result == {"app_env": "dev", "duration_ms": 12}


def test_logging_with_safe_extra_does_not_raise():
    """使用 safe_extra 后，即便传入保留属性名也不应抛异常。"""
    logger = logging.getLogger("test.safe_extra")
    # 不应抛出 KeyError: Attempt to overwrite 'created' in LogRecord
    logger.info("就绪", extra=safe_extra(created=True))


def test_raw_reserved_key_would_raise():
    """反向验证：不使用 safe_extra 时确实会抛异常（说明防护是必要的）。"""
    import pytest

    logger = logging.getLogger("test.raw_reserved")
    with pytest.raises(KeyError):
        logger.info("就绪", extra={"created": True})


def test_reserved_set_covers_common_attrs():
    for attr in ("created", "name", "module", "args", "msg", "levelname", "process"):
        assert attr in LOG_RECORD_RESERVED


def test_json_formatter_includes_extra_fields():
    """extra 字段应出现在 JSON 输出中。"""
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.trace_custom = "abc"  # type: ignore[attr-defined]

    out = JsonFormatter().format(record)
    assert '"message":"hello"' in out.replace(" ", "")
    assert "trace_custom" in out
