"""切片服务。

策略见 prd/02-architecture.md §2.1：
    CHUNK_SIZE_TOKENS=600，CHUNK_OVERLAP_TOKENS=80
    保留标题 / 章节 / 页码结构；表格转 Markdown

结构头用于增强 Embedding，但 payload.content 只存纯正文（避免污染引用展示）。

实现阶段：M1。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.services.parser_service import ParsedBlock

# 默认分词器：tiktoken cl100k_base（text-embedding-3-small 所用编码）。
# 编码文件首次使用需下载，离线环境退化为字符近似计数（约 4 字符/token）。
_DEFAULT_ENCODING = "cl100k_base"
_CHARS_PER_TOKEN_FALLBACK = 4

_token_counter: Callable[[str], int] | None = None

# 句子边界：中英文句读与换行。英文句点要求后跟空白，避免切开 3.5 这类小数
_SENTENCE_SPLIT_RE = r"(?<=[。！？；!?;])\s*|(?<=\.)\s+|\n+"


@dataclass
class ChunkDraft:
    """切片草稿：content 为纯正文，结构信息仅用于 embedding 文本与 payload。"""

    content: str
    token_count: int
    page: int | None = None
    section: str | None = None


@dataclass
class _Unit:
    """切分原子单位（句子 / 表格块）。"""

    content: str
    page: int | None = None
    section: str | None = None


def _make_tiktoken_counter(encoding) -> Callable[[str], int]:
    """包装 tiktoken 编码器为计数函数（禁止对特殊 token 抛错）。"""

    def _count(text: str) -> int:
        return len(encoding.encode(text, disallowed_special=()))

    return _count


def get_token_counter() -> Callable[[str], int]:
    """获取全局分词计数器（单次初始化）。"""
    global _token_counter
    if _token_counter is None:
        try:
            import tiktoken

            encoding = tiktoken.get_encoding(_DEFAULT_ENCODING)
            _token_counter = _make_tiktoken_counter(encoding)
        except Exception:  # noqa: BLE001  # 离线 / 编码不可用时退化
            _token_counter = _fallback_count
    return _token_counter


def count_tokens(text: str) -> int:
    """统计文本 token 数。"""
    return get_token_counter()(text)


def build_embedding_text(
    title: str | None, section: str | None, page: int | None, body: str
) -> str:
    """拼装用于向量化的文本（含结构头）。

    结构头只增强 Embedding 语义；payload.content 仍存纯正文（prd/02 §2.1）。
    """
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


def _fallback_count(text: str) -> int:
    """无 tiktoken 时的近似计数。"""
    if not text:
        return 0
    return (len(text) + _CHARS_PER_TOKEN_FALLBACK - 1) // _CHARS_PER_TOKEN_FALLBACK


def split_blocks(
    blocks: Sequence[ParsedBlock],
    size_tokens: int = 600,
    overlap_tokens: int = 80,
    count_fn: Callable[[str], int] | None = None,
) -> list[ChunkDraft]:
    """将解析块切片。

    - 句子为原子单位贪心装包，超过 size_tokens 即切分；
    - 相邻切片保留约 overlap_tokens 的重叠（取前一包尾部单位）；
    - 表格块尽量保持完整（不跨块切开），超长时退化为硬切；
    - count_fn 可注入（测试用确定性计数），默认走 tiktoken。
    """
    if size_tokens <= 0:
        raise ValueError("size_tokens 必须为正数")
    overlap = min(overlap_tokens, size_tokens // 2)
    counter = count_fn or get_token_counter()

    chunks: list[ChunkDraft] = []
    for block in blocks:
        body = block.content.strip()
        if not body:
            continue
        if block.is_table and counter(body) <= size_tokens:
            # 表格完整性优先
            chunks.append(
                ChunkDraft(
                    content=body,
                    token_count=counter(body),
                    page=block.page,
                    section=block.section,
                )
            )
            continue
        chunks.extend(_pack_units(_block_to_units(block), size_tokens, overlap, counter))
    return chunks


# ---------------- 内部实现 ----------------


def _block_to_units(block: ParsedBlock) -> list[_Unit]:
    """把一个解析块拆成原子单位（句子）。"""
    sentences = [s.strip() for s in re.split(_SENTENCE_SPLIT_RE, block.content) if s.strip()]
    return [
        _Unit(content=sentence, page=block.page, section=block.section) for sentence in sentences
    ]


def _split_long_unit(unit: _Unit, size_tokens: int, counter: Callable[[str], int]) -> list[_Unit]:
    """单句超过 size_tokens 时按字符窗口硬切（二分逼近上限）。"""
    pieces: list[_Unit] = []
    remaining = unit.content
    while remaining:
        if counter(remaining) <= size_tokens:
            pieces.append(_Unit(remaining, unit.page, unit.section))
            break
        lo, hi, best = 1, len(remaining), 0
        while lo <= hi:
            mid = (lo + hi) // 2
            if counter(remaining[:mid]) <= size_tokens:
                best, lo = mid, mid + 1
            else:
                hi = mid - 1
        if best <= 0:  # 极端情况：单 token 超过上限，强制对半
            best = max(1, len(remaining) // 2)
        pieces.append(_Unit(remaining[:best].rstrip(), unit.page, unit.section))
        remaining = remaining[best:].lstrip()
    return [piece for piece in pieces if piece.content]


def _pack_units(
    units: Sequence[_Unit],
    size_tokens: int,
    overlap_tokens: int,
    counter: Callable[[str], int],
) -> list[ChunkDraft]:
    """贪心装包 + 尾部重叠。"""
    prepared: list[_Unit] = []
    for unit in units:
        if counter(unit.content) > size_tokens:
            prepared.extend(_split_long_unit(unit, size_tokens, counter))
        else:
            prepared.append(unit)

    packs: list[list[_Unit]] = []
    current: list[_Unit] = []
    current_tokens = 0
    for unit in prepared:
        unit_tokens = counter(unit.content)
        if current and current_tokens + unit_tokens > size_tokens:
            packs.append(current)
            tail = _tail_for_overlap(current, overlap_tokens, counter)
            tail_tokens = sum(counter(u.content) for u in tail)
            # 重叠后仍超限（单位大于重叠预算）时放弃重叠，保证切片不超上限
            if tail and tail_tokens + unit_tokens <= size_tokens:
                current, current_tokens = tail, tail_tokens
            else:
                current, current_tokens = [], 0
        current.append(unit)
        current_tokens += unit_tokens
    if current:
        packs.append(current)

    return [
        ChunkDraft(
            content="\n".join(u.content for u in pack),
            token_count=counter("\n".join(u.content for u in pack)),
            page=pack[0].page,
            section=pack[0].section,
        )
        for pack in packs
    ]


def _tail_for_overlap(
    pack: list[_Unit], overlap_tokens: int, counter: Callable[[str], int]
) -> list[_Unit]:
    """从上一包尾部取不超过 overlap_tokens 的单位作为重叠。"""
    tail: list[_Unit] = []
    tail_tokens = 0
    for unit in reversed(pack):
        unit_tokens = counter(unit.content)
        if tail_tokens + unit_tokens > overlap_tokens:
            break
        tail.insert(0, unit)
        tail_tokens += unit_tokens
    return tail


__all__ = [
    "ChunkDraft",
    "build_embedding_text",
    "count_tokens",
    "get_token_counter",
    "split_blocks",
]
