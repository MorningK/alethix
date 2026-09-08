"""配置解析测试。

重点验证 LLM 与 Embedding 端点的「专用变量优先、留空回退通用」解析
（prd/02-architecture.md §5.1.1，AG-7.1 / AG-7.2）。
"""

from __future__ import annotations

from app.core.config import Settings

# 用例必须与真实 .env 隔离：否则开发者本地配置（如启用本地 TEI）
# 会污染断言结果，导致同样的代码在不同机器上测试结论不一致。
NO_ENV_FILE = {"_env_file": None}


def test_defaults_fallback_to_common():
    """专用变量留空时，应回退到通用变量。"""
    s = Settings(
        openai_base_url="https://api.openai.com/v1",
        openai_api_key="common-key",
        **NO_ENV_FILE,
    )
    assert s.resolved_llm_base_url == "https://api.openai.com/v1"
    assert s.resolved_llm_api_key == "common-key"
    assert s.resolved_embedding_base_url == "https://api.openai.com/v1"
    assert s.resolved_embedding_api_key == "common-key"


def test_specific_overrides_common():
    """专用变量非空时优先，且不影响另一端。"""
    s = Settings(
        openai_base_url="https://api.openai.com/v1",
        openai_api_key="common-key",
        embedding_base_url="http://localhost:8080/v1",
        embedding_api_key="tei-key",
        **NO_ENV_FILE,
    )
    # Embedding 走本地 TEI
    assert s.resolved_embedding_base_url == "http://localhost:8080/v1"
    assert s.resolved_embedding_api_key == "tei-key"
    # LLM 不受影响，仍走通用值
    assert s.resolved_llm_base_url == "https://api.openai.com/v1"
    assert s.resolved_llm_api_key == "common-key"


def test_extensions_parsing():
    s = Settings(doc_allowed_extensions="pdf, MD , txt ", **NO_ENV_FILE)
    assert s.allowed_extensions == ["pdf", "md", "txt"]
    assert s.max_file_size_bytes == 50 * 1024 * 1024
