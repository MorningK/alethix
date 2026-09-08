"""依赖注入。

提供：数据库会话、当前用户身份、配置、服务实例。
身份一律取自 X-User-Id 请求头，不信任 Body/Query 传入的值（NFR-3.2）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header

from app.core.config import Settings, get_settings
from app.core.errors import ERR_UNAUTHORIZED, ApiError
from app.db.postgres import get_session as _get_session


async def get_settings_dep() -> Settings:
    return get_settings()


async def get_user_id(x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None) -> str:
    """提取当前用户身份。缺失时返回 401。"""
    if not x_user_id:
        raise ApiError(code=ERR_UNAUTHORIZED, message="缺少 X-User-Id 请求头", status=401)
    return x_user_id


async def session_dep() -> AsyncIterator[None]:
    """占位：真实实现由 app.db.postgres.get_session 提供。"""
    yield


# 供路由直接复用的类型别名
DbSession = Annotated[object, Depends(_get_session)]
CurrentUserId = Annotated[str, Depends(get_user_id)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
