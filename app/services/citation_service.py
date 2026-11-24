"""引用构造与白名单校验。

quote 只从命中切片的 payload 截取，chunk_id 只接受检索命中集合中的值，
杜绝模型编造引用（AG-1.21 ~ AG-1.23）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.core.config import Settings, get_settings
from app.schemas.document import Citation
from app.services.retrieval_service import RetrievedChunk

DEFAULT_QUOTE_CHARS = 300


def build_citations(
    hits: Sequence[RetrievedChunk],
    filename_by_document: Mapping[str, str],
    used_chunk_ids: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
) -> tuple[list[Citation], int]:
    """返回白名单引用与被剔除的伪造 chunk_id 数量。"""
    s = settings or get_settings()
    max_chars = s.agent_max_chunk_chars or DEFAULT_QUOTE_CHARS
    quote_chars = min(max_chars, DEFAULT_QUOTE_CHARS)

    hit_by_id = {hit.chunk_id: hit for hit in hits}
    declared = list(dict.fromkeys(used_chunk_ids or []))
    ordered_ids = [chunk_id for chunk_id in declared if chunk_id in hit_by_id]
    filtered_count = len(declared) - len(ordered_ids)

    if not declared:
        ordered_ids = [hit.chunk_id for hit in hits]

    citations: list[Citation] = []
    for ordinal, chunk_id in enumerate(ordered_ids, start=1):
        hit = hit_by_id[chunk_id]
        content = hit.content.strip()
        quote = content[:quote_chars]
        if len(content) > quote_chars:
            quote = f"{quote}…"
        citations.append(
            Citation(
                document_id=hit.document_id,
                chunk_id=hit.chunk_id,
                filename=(filename_by_document.get(hit.document_id) or hit.title or "未知文档"),
                page=hit.page,
                section=hit.section,
                quote=quote,
                score=hit.score,
            )
        )
    return citations, filtered_count


__all__ = ["build_citations"]
