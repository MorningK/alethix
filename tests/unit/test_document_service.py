"""文档服务测试（M1）。

覆盖纯函数与校验逻辑：content_hash、存储路径、上传校验（白名单 / 魔数 / 大小）、
配额边界、任务状态快照。数据库访问函数（create/get/list …）由接口测试以打桩方式覆盖。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.models.document import Document
from app.services.document_service import (
    MAX_DOCUMENTS_PER_USER,
    build_storage_path,
    check_quota,
    compute_content_hash,
    save_upload_file,
    task_payload,
    validate_upload,
)

NO_ENV_FILE = {"_env_file": None}


def _settings() -> Settings:
    return Settings(doc_allowed_extensions="pdf,md,txt", **NO_ENV_FILE)


# ---------------- 哈希与路径 ----------------


def test_content_hash_is_sha256_of_bytes():
    import hashlib

    data = b"alethix"
    assert compute_content_hash(data) == hashlib.sha256(data).hexdigest()
    assert len(compute_content_hash(data)) == 64
    assert compute_content_hash(data) == compute_content_hash(b"alethix")
    assert compute_content_hash(b"a") != compute_content_hash(b"b")


def test_build_storage_path_uses_document_id():
    s = _settings()
    path = build_storage_path(s, "doc-uuid", "pdf")
    assert path.endswith("/doc-uuid.pdf")
    assert "storage" not in path  # 不泄露用户原始文件名


def test_save_upload_file_roundtrip(tmp_path):
    s = Settings(storage_path=str(tmp_path / "files"), **NO_ENV_FILE)
    path = save_upload_file(s, "doc-uuid", "md", "# 标题".encode())
    assert path.endswith("doc-uuid.md")
    with open(path, "rb") as f:
        assert f.read() == "# 标题".encode()


# ---------------- validate_upload ----------------


def test_validate_upload_accepts_pdf():
    s = _settings()
    assert validate_upload("report.pdf", b"%PDF-1.4 binary", s) == "pdf"


def test_validate_upload_accepts_md():
    s = _settings()
    assert validate_upload("notes.MD", b"# hello", s) == "md"


def test_validate_upload_rejects_empty_file():
    with pytest.raises(ApiError) as exc:
        validate_upload("a.txt", b"", _settings())
    assert exc.value.code == "4001003"


def test_validate_upload_rejects_oversize():
    s = Settings(doc_max_file_size_mb=1, **NO_ENV_FILE)
    with pytest.raises(ApiError) as exc:
        validate_upload("a.txt", b"x" * (1024 * 1024 + 1), s)
    assert exc.value.code == "4001003"


def test_validate_upload_rejects_unknown_extension():
    with pytest.raises(ApiError) as exc:
        validate_upload("a.docx", b"PK...", _settings())
    assert exc.value.code == "4001003"


def test_validate_upload_rejects_magic_mismatch():
    with pytest.raises(ApiError) as exc:
        validate_upload("a.pdf", b"%PNG fake", _settings())
    assert exc.value.code == "4001003"


def test_validate_upload_rejects_empty_filename():
    with pytest.raises(ApiError) as exc:
        validate_upload("   ", b"%PDF-1.4", _settings())
    assert exc.value.code == "4001001"


# ---------------- 配额 ----------------


def test_quota_allows_below_limit():
    check_quota(MAX_DOCUMENTS_PER_USER - 1)  # 不抛异常


def test_quota_rejects_at_limit():
    with pytest.raises(ApiError) as exc:
        check_quota(MAX_DOCUMENTS_PER_USER)
    assert exc.value.code == "4001005"


# ---------------- task_payload ----------------


def _document(**kwargs) -> Document:
    base = dict(
        id="3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d",
        user_id="9f2c1a8e-3b4d-4f6a-8c21-0e5d7a9b1c34",
        filename="report.pdf",
        content_hash="h" * 64,
        source_format="pdf",
        status="ready",
        chunk_count=12,
        page_count=3,
        ready_at=None,
    )
    base.update(kwargs)
    return Document(**base)


def test_task_payload_ready():
    payload = task_payload(_document())
    assert payload["document_id"] == "3a71b0c2-5e6f-4a8b-9c1d-2e3f4a5b6c7d"
    assert payload["status"] == "ready"
    assert payload["chunk_count"] == 12
    assert payload["error"] is None
    assert "updated_at" in payload


def test_task_payload_failed_with_error():
    payload = task_payload(_document(status="failed", error_code="4001004", error_message="空文档"))
    assert payload["status"] == "failed"
    assert payload["error"] == {"code": "4001004", "message": "空文档"}
