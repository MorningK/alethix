"""切片服务（占位）。

策略见 prd/02-architecture.md §2.1：
    CHUNK_SIZE_TOKENS=600，CHUNK_OVERLAP_TOKENS=80
    保留标题 / 章节 / 页码结构；表格转 Markdown

结构头用于增强 Embedding，但 payload.content 只存纯正文（避免污染引用展示）。

实现阶段：M1。
"""

from __future__ import annotations


def build_embedding_text(
    title: str | None, section: str | None, page: int | None, body: str
) -> str:
    """拼装用于向量化的文本（含结构头）。"""
    lines = []
    if title:
        lines.append(f"【文档标题】{title}")
    if section:
        lines.append(f"【章节】{section}")
    if page is not None:
        lines.append(f"【页码】{page}")
    if lines:
        lines.append("")
    lines.append(body)
    return "\n".join(lines)


def split_blocks(blocks: list, size_tokens: int, overlap_tokens: int) -> list[str]:
    """将解析块切片。待 M1 实现。"""
    raise NotImplementedError("待 M1 实现")
