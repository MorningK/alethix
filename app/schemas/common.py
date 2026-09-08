"""通用 DTO。

错误响应结构见 prd/05-api-spec.md §1.5；
分页结构见 §1.3。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """分页响应。"""

    items: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class NotImplementedResponse(BaseModel):
    """占位路由的统一响应，便于前端识别未完成接口。"""

    detail: str
    api: str
