"""PostgreSQL asyncpg 引擎的 JSONB 绑定层回归测试。

M2 曾使用 identity json_serializer 导致 list/dict 原样进入 asyncpg codec，
在真实写库时因缺少 .encode() 而失败。这里通过应用实际配置的引擎验证绑定结果。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.dialects.postgresql import JSONB

from app.core.config import Settings
from app.db.postgres import close_postgres, get_engine, init_postgres


@pytest.fixture(scope="module")
def bind_processor():
    init_postgres(
        Settings(
            app_env="dev",
            postgres_dsn="postgresql+asyncpg://user:pass@localhost/db",
        )
    )
    yield JSONB().bind_processor(get_engine().dialect)
    asyncio.run(close_postgres())


@pytest.mark.parametrize(
    "value, expected",
    [
        ([], "[]"),
        (["a", "b"], '["a", "b"]'),
        ({"queries": ["风险"]}, r'{"queries": ["\u98ce\u9669"]}'),
    ],
)
def test_jsonb_values_are_serialized_to_strings(bind_processor, value, expected):
    bound = bind_processor(value)
    assert isinstance(bound, str)
    assert bound == expected
    assert isinstance(bound.encode("utf-8"), bytes)
