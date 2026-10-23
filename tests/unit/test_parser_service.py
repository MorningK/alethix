"""解析服务测试（M1）。

覆盖：格式识别（白名单 / 魔数 / UTF-8 校验）、PDF 解析（页码 / 标题 / 空文档 /
加密）、Markdown 章节切分、表格转 Markdown（含 to_markdown 不可用时的退化路径）。
"""

from __future__ import annotations

import pytest

from app.core.errors import ApiError
from app.services.parser_service import (
    ParseResult,
    _extract_pdf_tables,
    detect_format,
    parse_document,
    parse_pdf,
    parse_text,
)

ALLOWED = ["pdf", "md", "txt"]
NO_ENV_FILE = {"_env_file": None}


def _make_pdf(
    path, *, text: str | None = "Hello world. Second sentence.", title: str | None = None
):
    """用 PyMuPDF 生成最小 PDF（默认字体仅支持 ASCII，测试文本用英文）。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text)
    if title:
        doc.set_metadata({"title": title})
    doc.save(str(path))
    doc.close()


# ---------------- detect_format ----------------


def test_detect_pdf_by_magic():
    assert detect_format("a.pdf", b"%PDF-1.7\n...", ALLOWED) == "pdf"


def test_detect_rejects_pdf_without_magic():
    with pytest.raises(ApiError) as exc:
        detect_format("fake.pdf", b"not a pdf at all", ALLOWED)
    assert exc.value.code == "4001003"


def test_detect_rejects_extension_not_in_whitelist():
    with pytest.raises(ApiError) as exc:
        detect_format("a.exe", b"MZ...", ALLOWED)
    assert exc.value.code == "4001003"


def test_detect_rejects_non_utf8_text():
    with pytest.raises(ApiError) as exc:
        detect_format("a.txt", b"\xff\xfe\x00\x01", ALLOWED)
    assert exc.value.code == "4001003"


def test_detect_md_and_txt():
    assert detect_format("a.MD", "# 标题".encode(), ALLOWED) == "md"
    assert detect_format("a.txt", "纯文本".encode(), ALLOWED) == "txt"


# ---------------- parse_text ----------------


def test_parse_text_splits_sections(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(
        "# 第一章\n这是第一段。\n\n这是第二段。\n\n## 1.1 小节\n小节内容在这里。\n",
        encoding="utf-8",
    )
    result = parse_text(str(path))

    assert isinstance(result, ParseResult)
    # 标题块与后续段落块都携带当前章节；章节在遇到新标题时切换
    sections = [b.section for b in result.blocks if b.section]
    assert sections == ["第一章", "第一章", "第一章", "1.1 小节", "1.1 小节"]
    assert any("这是第一段" in b.content for b in result.blocks)
    assert all(b.page is None for b in result.blocks)


def test_parse_text_rejects_empty(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("   \n\n  \n", encoding="utf-8")
    with pytest.raises(ApiError) as exc:
        parse_text(str(path))
    assert exc.value.code == "4001004"


# ---------------- parse_pdf ----------------


@pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("fitz") is None,
    reason="PyMuPDF 未安装",
)
def test_parse_pdf_extracts_text_pages_and_title(tmp_path):
    path = tmp_path / "doc.pdf"
    _make_pdf(path, text="First page content. Second sentence.", title="Test Doc")

    result = parse_pdf(str(path))

    assert result.page_count == 1
    assert result.title == "Test Doc"
    joined = "".join(b.content for b in result.blocks)
    assert "First page content" in joined
    assert all(b.page == 1 for b in result.blocks)


@pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("fitz") is None,
    reason="PyMuPDF 未安装",
)
def test_parse_pdf_rejects_empty_document(tmp_path):
    path = tmp_path / "empty.pdf"
    _make_pdf(path, text=None)

    with pytest.raises(ApiError) as exc:
        parse_pdf(str(path))
    assert exc.value.code == "4001004"


@pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("fitz") is None,
    reason="PyMuPDF 未安装",
)
def test_parse_pdf_rejects_encrypted(tmp_path):
    import fitz

    path = tmp_path / "encrypted.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Encrypted content here.")
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_128, user_pw="secret")
    doc.close()

    with pytest.raises(ApiError) as exc:
        parse_pdf(str(path))
    assert exc.value.code == "4001004"


def test_parse_document_dispatch(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("纯文本内容。", encoding="utf-8")
    result = parse_document(str(path), "txt")
    assert any("纯文本内容" in b.content for b in result.blocks)

    with pytest.raises(ApiError) as exc:
        parse_document(str(path), "docx")
    assert exc.value.code == "4001003"


# ---------------- 表格转 Markdown ----------------


class _FakeTableMd:
    def to_markdown(self) -> str:
        return "| 列A | 列B |\n| --- | --- |\n| 1 | 2 |"


class _FakeTableExtract:
    def to_markdown(self) -> str:
        raise AttributeError("旧版本无此方法")

    def extract(self):
        return [["列A", "列B"], ["1", "2"]]


class _FakeFinder:
    def __init__(self, tables):
        self.tables = tables


class _FakePage:
    def __init__(self, tables):
        self._finder = _FakeFinder(tables)

    def find_tables(self):
        return self._finder


class _BrokenPage:
    def find_tables(self):
        raise RuntimeError("页面无表格能力")


def test_extract_tables_to_markdown():
    result = _extract_pdf_tables(_FakePage([_FakeTableMd()]))
    assert result == ["| 列A | 列B |\n| --- | --- |\n| 1 | 2 |"]


def test_extract_tables_fallback_to_extract():
    result = _extract_pdf_tables(_FakePage([_FakeTableExtract()]))
    assert result == ["| 列A | 列B |\n| 1 | 2 |"]


def test_extract_tables_swallows_errors():
    assert _extract_pdf_tables(_BrokenPage()) == []
    assert _extract_pdf_tables(_FakePage([])) == []
