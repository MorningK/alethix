"""文档解析服务（占位）。

按格式分派解析器（prd/02-architecture.md §3.1）：
    PDF → PyMuPDF（保留页码）
    DOCX → python-docx
    Markdown / TXT → 直接读取
    HTML → Trafilatura / BeautifulSoup

输出：正文、标题、页码、章节结构。表格转为 Markdown，不得丢弃。

实现阶段：M1。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParsedBlock:
    """解析后的文本块，携带结构信息。"""

    content: str
    page: int | None = None
    section: str | None = None
    is_table: bool = False


def parse_pdf(path: str) -> list[ParsedBlock]:
    """解析 PDF，保留页码与章节。待 M1 实现。"""
    raise NotImplementedError("待 M1 实现：PyMuPDF")


def parse_docx(path: str) -> list[ParsedBlock]:
    """解析 Word。待 M1 实现。"""
    raise NotImplementedError("待 M1 实现：python-docx")


def parse_text(path: str) -> list[ParsedBlock]:
    """解析 Markdown / TXT。待 M1 实现。"""
    raise NotImplementedError("待 M1 实现")
