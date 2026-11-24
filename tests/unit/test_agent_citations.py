"""引用白名单与原文重建测试。"""

from __future__ import annotations

from app.core.config import Settings
from app.services.citation_service import build_citations
from app.services.retrieval_service import RetrievedChunk


def test_citation_uses_original_content_and_filters_fake_ids():
    settings = Settings(_env_file=None, agent_max_chunk_chars=50)
    hits = [
        RetrievedChunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            content="合规风险原文" * 20,
            score=0.9,
            page=3,
            section="风险",
            title="报告.pdf",
        )
    ]

    citations, filtered = build_citations(
        hits,
        {"doc-1": "报告.pdf"},
        ["chunk-1", "fake-chunk"],
        settings=settings,
    )

    assert filtered == 1
    assert len(citations) == 1
    assert citations[0].quote.startswith("合规风险原文")
    assert citations[0].quote.endswith("…")
    assert citations[0].filename == "报告.pdf"
    assert citations[0].page == 3


def test_no_declared_ids_falls_back_to_all_hits():
    settings = Settings(_env_file=None)
    hits = [
        RetrievedChunk(chunk_id="a", document_id="doc-1", content="A", score=0.8),
        RetrievedChunk(chunk_id="b", document_id="doc-1", content="B", score=0.7),
    ]
    citations, filtered = build_citations(hits, {}, [], settings=settings)
    assert [item.chunk_id for item in citations] == ["a", "b"]
    assert filtered == 0
