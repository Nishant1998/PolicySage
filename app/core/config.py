from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "PolicySage"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    langsmith_enabled: bool = False
    langsmith_debug_content: bool = False
    langsmith_trace_sample_rate: float = Field(default=1.0, ge=0, le=1)
    langsmith_api_key: SecretStr = SecretStr("")
    langsmith_agent_id: str = "policysage"
    langsmith_agent_environment: Literal["local", "development", "staging", "production"] = "local"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    llm_input_usd_per_million: float | None = Field(default=None, ge=0)
    llm_output_usd_per_million: float | None = Field(default=None, ge=0)
    llm_cached_input_usd_per_million: float | None = Field(default=None, ge=0)

    openai_api_key: SecretStr = Field(min_length=1)
    tavily_api_key: SecretStr = SecretStr("")
    brave_api_key: SecretStr = SecretStr("")
    web_search_provider: Literal["brave", "tavily"] = "tavily"
    qdrant_api_key: SecretStr = SecretStr("")
    admin_api_key: SecretStr = SecretStr("")

    openai_model: str = "gpt-6-luna"
    llm_provider: Literal["openai"] = "openai"
    web_search_enabled: bool = True
    embedding_model: str = "text-embedding-3-small"
    vector_db_provider: Literal["qdrant"] = "qdrant"
    qdrant_url: str = ""
    qdrant_collection: str = "insurance-kb"

    top_k: int = Field(default=10, ge=1, le=10)
    max_retries: int = Field(default=2, ge=0, le=2)
    request_timeout: float = Field(default=60.0, gt=0)
    chat_timeout: float = Field(default=180.0, ge=10, le=300)
    chat_requests_per_minute: int = Field(default=6, ge=1)
    daily_chat_limit: int = Field(default=30, ge=1)
    monthly_chat_limit: int = Field(default=300, ge=1)
    public_chat_enabled: bool = True
    public_pdf_downloads_enabled: bool = False
    max_searches_per_chat: int = Field(default=6, ge=1, le=12)
    max_web_attempts_per_chat: int = Field(default=4, ge=0, le=6)
    max_concurrent_chats: int = Field(default=2, ge=1, le=8)
    max_answer_tokens: int = Field(default=1500, ge=128, le=4096)
    max_evidence_tokens: int = Field(default=8000, ge=1000, le=16000)
    max_request_tokens: int = Field(default=72000, ge=4000)
    max_prompt_tokens: int = Field(default=14000, ge=1000)
    max_history_tokens: int = Field(default=2000, ge=0)
    max_question_tokens: int = Field(default=1024, ge=128)
    chunk_tokens: int = Field(default=450, ge=128, le=700)
    chunk_overlap_tokens: int = Field(default=90, ge=0, le=150)
    chunk_min_tokens: int = Field(default=200, ge=1, le=450)
    chunk_max_tokens: int = Field(default=650, ge=128, le=800)

    audit_db_path: Path = BASE_DIR / "data" / "audit.db"
    kb_dir: Path = BASE_DIR / "data" / "kb"
    usage_db_path: Path = BASE_DIR / "data" / "usage.db"
    semantic_cache_path: Path = BASE_DIR / "data" / "semantic_cache.db"
    kb_managed: bool = True
    kb_database_url: SecretStr = SecretStr("")
    kb_s3_endpoint: str = ""
    kb_s3_region: str = ""
    kb_s3_bucket: str = ""
    kb_s3_access_key_id: SecretStr = SecretStr("")
    kb_s3_secret_access_key: SecretStr = SecretStr("")
    kb_admin_username: str = "admin"
    kb_admin_password: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
