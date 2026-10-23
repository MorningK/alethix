"""文档解析服务。

按格式分派解析器（prd/02-architecture.md §3.1）：
    PDF → PyMuPDF（保留页码）
    DOCX → python-docx（不在 MVP 白名单，暂占位）
    Markdown / TXT → 直接读取
    HTML → Trafilatura / BeautifulSoup（不在 MVP 白名单，暂占位）

输出：正文块、标题、页码、章节结构。表格转为 Markdown，不得丢弃。

实现阶段：M1。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import ERR_DOC_TYPE_OR_SIZE, ERR_DOC_UNREADABLE, ApiError

# 文本格式解码统一按 UTF-8（容忍 BOM）；解码失败按不可读文档处理
_TEXT_ENCODING = "utf-8-sig"

# Markdown 标题行：`## 标题`
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
# 编号标题行：`3.2 行业风险` / `第三章 方法`（正文字号无差异时的兜底识别）
_NUMBERED_HEADING_RE = re.compile(
    r"^(\d+(?:\.\d+)*)[\.、\s]\s*\S|^第[一二三四五六七八九十百]+[章节部分篇]\s*\S"
)


@dataclass
class ParsedBlock:
    """解析后的文本块，携带结构信息。"""

    content: str
    page: int | None = None
    section: str | None = None
    is_table: bool = False


@dataclass
class ParseResult:
    """单篇文档的解析结果。"""

    blocks: list[ParsedBlock] = field(default_factory=list)
    title: str | None = None
    page_count: int | None = None


def detect_format(
    filename: str, data: bytes, allowed_extensions: Sequence[str] | None = None
) -> str:
    """识别真实格式：扩展名白名单 + 魔数校验，不信任扩展名（API-2 约束）。

    返回归一化格式：pdf / md / txt。
    """
    allowed = {ext.lower() for ext in allowed_extensions} if allowed_extensions else None
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not ext:
        raise ApiError(ERR_DOC_TYPE_OR_SIZE, "文件缺少扩展名，无法识别格式", status=400)
    if allowed is not None and ext not in allowed:
        raise ApiError(ERR_DOC_TYPE_OR_SIZE, f"不支持的文件类型：{ext}", status=400)

    if ext == "pdf":
        if not data.startswith(b"%PDF-"):
            raise ApiError(ERR_DOC_TYPE_OR_SIZE, "文件内容与声明格式（PDF）不匹配", status=400)
        return "pdf"
    if ext in ("md", "markdown"):
        _ensure_text_decodable(data)
        return "md"
    if ext == "txt":
        _ensure_text_decodable(data)
        return "txt"
    raise ApiError(ERR_DOC_TYPE_OR_SIZE, f"不支持的文件类型：{ext}", status=400)


def parse_document(path: str, source_format: str) -> ParseResult:
    """按格式分派解析器。"""
    if source_format == "pdf":
        return parse_pdf(path)
    if source_format in ("md", "txt"):
        return parse_text(path)
    raise ApiError(ERR_DOC_TYPE_OR_SIZE, f"暂不支持的文档格式：{source_format}", status=400)


def parse_pdf(path: str) -> ParseResult:
    """解析 PDF：逐页提取正文 / 章节 / 表格，保留页码与文档标题。"""
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(ERR_DOC_UNREADABLE, f"PDF 打开失败：{exc}", status=400) from exc

    try:
        if doc.needs_pass:
            raise ApiError(ERR_DOC_UNREADABLE, "加密 PDF 暂不支持，请先解密后上传", status=400)

        metadata_title = (doc.metadata or {}).get("title") or None
        blocks: list[ParsedBlock] = []
        section: str | None = None
        for page_no in range(1, doc.page_count + 1):
            page = doc[page_no - 1]
            section = _extract_pdf_page(page, page_no, section, blocks)
        page_count = doc.page_count
    finally:
        doc.close()

    if not _has_text(blocks):
        raise ApiError(
            ERR_DOC_UNREADABLE,
            "未能提取到可检索的文本（文档可能为扫描件或纯图片）",
            status=400,
        )
    return ParseResult(blocks=blocks, title=metadata_title, page_count=page_count)


def parse_text(path: str) -> ParseResult:
    """解析 Markdown / TXT：按标题切分章节，按空行聚合段落。"""
    try:
        text = Path(path).read_text(encoding=_TEXT_ENCODING)
    except (OSError, UnicodeDecodeError) as exc:
        raise ApiError(ERR_DOC_UNREADABLE, f"文本文件读取失败：{exc}", status=400) from exc

    blocks: list[ParsedBlock] = []
    section: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if buffer:
            content = "\n".join(buffer).strip()
            if content:
                blocks.append(ParsedBlock(content=content, section=section))
            buffer = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = _MD_HEADING_RE.match(line)
        if heading:
            flush()
            section = heading.group(2).strip()
            blocks.append(ParsedBlock(content=section, section=section))
            continue
        if not line:
            flush()
            continue
        buffer.append(line)
    flush()

    if not _has_text(blocks):
        raise ApiError(ERR_DOC_UNREADABLE, "文档内容为空，未能提取到可检索的文本", status=400)
    return ParseResult(blocks=blocks, title=None, page_count=None)


def parse_docx(path: str) -> list[ParsedBlock]:
    """解析 Word。不在 MVP 白名单（pdf/md/txt），待白名单扩展后实现。"""
    raise NotImplementedError("待 docx 纳入白名单后实现：python-docx")


# ---------------- 内部实现 ----------------


def _ensure_text_decodable(data: bytes) -> None:
    """文本格式必须可按 UTF-8 解码，否则视为伪造扩展名（4001003）。"""
    try:
        data.decode(_TEXT_ENCODING)
    except UnicodeDecodeError as exc:
        raise ApiError(
            ERR_DOC_TYPE_OR_SIZE, "文件不是有效的 UTF-8 文本，与声明格式不匹配", status=400
        ) from exc


def _has_text(blocks: list[ParsedBlock]) -> bool:
    """是否存在非空白正文（空文档 / 扫描件 / 纯图片 → 4001004）。"""
    return any(block.content.strip() for block in blocks)


def _extract_pdf_page(
    page, page_no: int, section: str | None, blocks: list[ParsedBlock]
) -> str | None:
    """提取单页：正文（带章节识别）+ 表格（转 Markdown）。返回跨页延续的章节。"""
    page_dict = page.get_text("dict")
    body_size = _body_font_size(page_dict)
    pending: list[str] = []

    def flush() -> None:
        nonlocal pending
        if pending:
            content = "\n".join(pending).strip()
            if content:
                blocks.append(ParsedBlock(content=content, page=page_no, section=section))
            pending = []

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:  # 非文本块（图片）跳过
            continue
        for line in block.get("lines", []):
            line_text = ""
            line_is_heading = False
            for span in line.get("spans", []):
                span_text = span.get("text", "")
                if not span_text.strip():
                    continue
                line_text += span_text
                if not line_is_heading and _is_heading(span, line_text, body_size):
                    line_is_heading = True
            line_text = line_text.strip()
            if not line_text:
                continue
            if line_is_heading:
                flush()
                section = line_text
                blocks.append(ParsedBlock(content=line_text, page=page_no, section=section))
            else:
                pending.append(line_text)
    flush()

    for table_md in _extract_pdf_tables(page):
        blocks.append(ParsedBlock(content=table_md, page=page_no, section=section, is_table=True))
    return section


def _body_font_size(page_dict: dict) -> float:
    """页面正文字号：取出现次数最多的 span 字号（四舍五入到 0.5）。"""
    sizes: Counter[float] = Counter()
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    sizes[round(float(span.get("size", 0)) * 2) / 2] += 1
    return sizes.most_common(1)[0][0] if sizes else 0.0


def _is_heading(span: dict, line_text: str, body_size: float) -> bool:
    """标题启发式：字号明显大于正文 / 加粗短行 / 编号标题行。"""
    text = span.get("text", "").strip()
    if not text or len(line_text) > 80:
        return False
    size = float(span.get("size", 0))
    if body_size and size >= body_size * 1.2:
        return True
    bold = bool(span.get("flags", 0) & 16)
    if bold and body_size and size >= body_size:
        return True
    return bool(_NUMBERED_HEADING_RE.match(line_text))


def _extract_pdf_tables(page) -> list[str]:
    """提取页面表格并转为 Markdown；版本不支持或失败时静默跳过。"""
    try:
        finder = page.find_tables()
    except Exception:  # noqa: BLE001  # PyMuPDF 版本差异或无表格能力
        return []
    tables_md: list[str] = []
    for table in getattr(finder, "tables", []):
        try:
            md = table.to_markdown()
        except Exception:  # noqa: BLE001  # 旧版本无 to_markdown，退化为 extract
            try:
                rows = table.extract()
            except Exception:  # noqa: BLE001
                continue
            md = "\n".join(
                "| " + " | ".join("" if c is None else str(c) for c in row) + " |" for row in rows
            )
        if md and md.strip():
            tables_md.append(md.strip())
    return tables_md


__all__ = [
    "ParseResult",
    "ParsedBlock",
    "detect_format",
    "parse_docx",
    "parse_document",
    "parse_pdf",
    "parse_text",
]
