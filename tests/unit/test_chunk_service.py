"""切片服务测试（M1）。

用可注入的确定性 count_fn（按空格计词）验证：
    - 切片不超过 size_tokens 上限
    - 相邻切片保留约 overlap_tokens 重叠
    - 页码 / 章节元数据保留
    - 表格块完整性优先，超长表格退化为硬切
    - 超长单句硬切且每片不超限
"""

from __future__ import annotations

from app.services.chunk_service import count_tokens, split_blocks
from app.services.parser_service import ParsedBlock


# 确定性计数器：1 词 = 1 token
def word_count(text: str) -> int:
    return len(text.split())


def _block(text: str, *, page=None, section=None, is_table=False) -> ParsedBlock:
    return ParsedBlock(content=text, page=page, section=section, is_table=is_table)


def test_chunks_respect_size_limit():
    sentences = [f"第{i}句话的内容。" for i in range(50)]  # 每句 1 token
    block = _block(" ".join(sentences), page=3, section="第二章")

    chunks = split_blocks([block], size_tokens=10, overlap_tokens=2, count_fn=word_count)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= 10
        assert chunk.page == 3
        assert chunk.section == "第二章"


def test_overlap_between_adjacent_chunks():
    # 带句读才会被切成独立句子单元（1 词 = 1 token）
    sentences = [f"s{i}。" for i in range(30)]
    block = _block("".join(sentences))

    chunks = split_blocks([block], size_tokens=10, overlap_tokens=3, count_fn=word_count)

    assert len(chunks) >= 2
    for prev, nxt in zip(chunks, chunks[1:]):
        prev_words = set(prev.content.split())
        nxt_words = set(nxt.content.split())
        assert prev_words & nxt_words, "相邻切片应存在重叠内容"


def test_table_block_kept_whole():
    table = "| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
    block = _block(table, page=7, section="表 1", is_table=True)

    chunks = split_blocks([block], size_tokens=600, overlap_tokens=80, count_fn=word_count)

    assert len(chunks) == 1
    assert chunks[0].content == table
    assert chunks[0].page == 7
    assert chunks[0].section == "表 1"
    assert chunks[0].token_count == len(table.split())


def test_oversized_table_falls_back_to_hard_split():
    table = " ".join(f"行{i}" for i in range(100))
    block = _block(table, is_table=True)

    chunks = split_blocks([block], size_tokens=10, overlap_tokens=2, count_fn=word_count)

    assert len(chunks) > 1
    assert all(c.token_count <= 10 for c in chunks)


def test_long_sentence_hard_split():
    long_sentence = "词" * 25  # 无空格，按词计数为 1 token 的超长单句
    block = _block(long_sentence)

    # 用字符计数模拟：每 1 字符 1 token
    chunks = split_blocks([block], size_tokens=10, overlap_tokens=2, count_fn=len)

    assert len(chunks) == 3
    assert all(c.token_count <= 10 for c in chunks)
    assert "".join(c.content for c in chunks) == long_sentence


def test_empty_blocks_skipped():
    chunks = split_blocks(
        [_block("   "), _block(""), _block("实际内容。")],
        size_tokens=10,
        overlap_tokens=2,
        count_fn=word_count,
    )
    assert len(chunks) == 1
    assert chunks[0].content == "实际内容。"


def test_invalid_size_raises():
    import pytest

    with pytest.raises(ValueError):
        split_blocks([_block("内容。")], size_tokens=0, count_fn=word_count)


def test_count_tokens_returns_int():
    # tiktoken 不可用时应退化为字符近似计数，任何环境都返回非负整数
    result = count_tokens("你好，世界。hello world")
    assert isinstance(result, int)
    assert result >= 0
