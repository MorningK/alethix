"""应用配置。

所有配置通过环境变量注入，禁止硬编码（NFR-3.6）。
变量清单见 prd/02-architecture.md §5。

LLM 与 Embedding 的端点/密钥采用「专用变量优先，留空回退通用变量」的两级配置，
对应 prd/02-architecture.md §5.1.1（AG-7.1 ~ AG-7.5）。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置模型。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------- 服务与观测 ----------------
    app_env: Literal["dev", "test", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    # ---------------- PostgreSQL ----------------
    postgres_dsn: str = "postgresql+asyncpg://alethix:alethix_dev_password@localhost:5432/alethix"
    postgres_pool_size: int = 20

    # ---------------- Redis ----------------
    redis_url: str = "redis://localhost:6379/0"

    # ---------------- Qdrant ----------------
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "document_chunks"

    # ---------------- 存储 ----------------
    storage_backend: Literal["local"] = "local"
    storage_path: str = "./data/files"

    # ---------------- LLM 与 Embedding：通用兜底 ----------------
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # ---------------- LLM 与 Embedding：专用（留空回退通用） ----------------
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None

    # ---------------- LLM ----------------
    llm_model: str = "gpt-4o-mini"
    llm_fallback_model: str | None = None
    llm_temperature: float = 0
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 3

    # ---------------- Embedding ----------------
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_batch_size: int = 64

    # ---------------- 智能体与检索 ----------------
    agent_max_iterations: int = 3
    agent_max_queries_per_round: int = 3
    agent_top_k_per_query: int = 10
    agent_score_threshold: float = 0.35
    agent_max_evidence_per_round: int = 12
    agent_max_chunk_chars: int = 1500
    agent_token_budget: int = 60000
    agent_timeout_seconds: int = 120
    agent_no_new_evidence_rounds: int = 1

    # ---------------- 文档处理 ----------------
    doc_max_file_size_mb: int = 50
    doc_allowed_extensions: str = "pdf,md,txt"
    chunk_size_tokens: int = 600
    chunk_overlap_tokens: int = 80
    ingest_max_retries: int = 3
    ingest_task_ttl_seconds: int = 86400

    # ---------------- 限流 ----------------
    rate_limit_ask_per_minute: int = 20
    rate_limit_upload_per_minute: int = 10

    # ---------------- 观测 ----------------
    otel_exporter_otlp_endpoint: str | None = None
    langsmith_api_key: str | None = None

    # ---------------- 端点解析（AG-7.1 / AG-7.2） ----------------
    @property
    def resolved_llm_base_url(self) -> str:
        """LLM 实际端点：专用变量优先，留空回退通用变量。"""
        return self.llm_base_url or self.openai_base_url

    @property
    def resolved_llm_api_key(self) -> str:
        return self.llm_api_key or self.openai_api_key

    @property
    def resolved_embedding_base_url(self) -> str:
        return self.embedding_base_url or self.openai_base_url

    @property
    def resolved_embedding_api_key(self) -> str:
        return self.embedding_api_key or self.openai_api_key

    @property
    def allowed_extensions(self) -> list[str]:
        """扩展名白名单，统一小写且去除空白。"""
        return [
            ext.strip().lower() for ext in self.doc_allowed_extensions.split(",") if ext.strip()
        ]

    @property
    def max_file_size_bytes(self) -> int:
        return self.doc_max_file_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """获取配置单例。测试时可用 get_settings.cache_clear() 重置。"""
    return Settings()
