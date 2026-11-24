"""PostgreSQL asyncpg 引擎的 JSONB 绑定层回归测试。

M2 曾使用 identity json_serializer 导致 list/dict 原样进入 asyncpg codec，
在真实写库时因缺少 .encode() 而失败。这里不连接数据库，只验证绑定结果。
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture(scope="module")
def bind_processor():
    engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/db")
    return JSONB().bind_processor(engine.dialect)


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
