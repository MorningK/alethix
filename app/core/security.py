"""文件安全校验与 Prompt 注入防护工具。

对应 NFR-3.3（类型白名单与魔数校验）、NFR-3.5（文档内容视为数据）。
本阶段提供纯函数工具，供 M1 文档入库流程调用。
"""

from __future__ import annotations

from app.core.errors import ERR_DOC_TYPE_OR_SIZE, ApiError

# 常见文件格式的魔数（文件头字节）
MAGIC_NUMBERS: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF",),
    "md": (),  # 纯文本，无固定魔数
    "txt": (),  # 纯文本，无固定魔数
    "docx": (b"PK\x03\x04",),  # OOXML 实为 zip
    "html": (b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML"),
}


def normalize_filename(filename: str) -> str:
    """规范化文件名，去除路径穿越字符与控制字符。"""
    cleaned = filename.replace("\\", "/").split("/")[-1]
    cleaned = "".join(ch for ch in cleaned if ch.isprintable())
    return cleaned.strip() or "unnamed"


def validate_extension(filename: str, allowed: list[str]) -> str:
    """校验扩展名是否在白名单内，返回小写扩展名。非法则抛 ApiError。"""
    lowered = filename.lower()
    ext = lowered.rsplit(".", 1)[-1] if "." in lowered else ""
    if ext not in allowed:
        ext_display = ext or "未知"
        raise ApiError(
            code=ERR_DOC_TYPE_OR_SIZE,
            message=f"不支持的文件类型：.{ext_display}",
            details={"allowed_extensions": allowed},
        )
    return ext


def validate_size(size_bytes: int, max_bytes: int) -> None:
    """校验文件大小。超限则抛 ApiError。"""
    if size_bytes <= 0:
        raise ApiError(code=ERR_DOC_TYPE_OR_SIZE, message="文件内容为空")
    if size_bytes > max_bytes:
        raise ApiError(
            code=ERR_DOC_TYPE_OR_SIZE,
            message=f"文件超过大小限制（最大 {max_bytes // 1024 // 1024} MB）",
            details={"max_size_mb": max_bytes // 1024 // 1024},
        )


def validate_magic_number(head: bytes, ext: str) -> bool:
    """校验文件头魔数是否与扩展名一致。

    纯文本格式（md / txt）无魔数，直接放行。
    """
    expected = MAGIC_NUMBERS.get(ext, ())
    if not expected:
        return True
    return any(head.startswith(sig) for sig in expected)


def wrap_untrusted_content(content: str) -> str:
    """将检索到的文档内容包裹为不可信数据块。

    配合 Prompt 中的 <security> 声明使用：被包裹的内容只能作为资料阅读，
    其中出现的任何指令都不得执行（NFR-3.5）。
    """
    return f"<context>\n{content}\n</context>"
