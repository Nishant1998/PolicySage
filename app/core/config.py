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

    openai_api_key: SecretStr = Field(min_length=1)
    tavily_api_key: SecretStr = Field(min_length=1)
    pinecone_api_key: SecretStr = Field(min_length=1)

    openai_model: str = "gpt-5-nano"
    embedding_model: str = "text-embedding-3-small"
    pinecone_index_name: str = "policysage"
    pinecone_namespace: str = "insurance-kb"

    top_k: int = Field(default=4, ge=1)
    max_retries: int = Field(default=2, ge=0, le=2)
    request_timeout: float = Field(default=30.0, gt=0)

    audit_db_path: Path = BASE_DIR / "data" / "audit.db"
    upload_dir: Path = BASE_DIR / "uploads"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
