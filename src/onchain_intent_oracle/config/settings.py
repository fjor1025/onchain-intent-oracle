"""Application settings using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    certora_key: Optional[str] = Field(default=None, alias="CERTORAKEY")
    etherscan_api_key: Optional[str] = Field(default=None, alias="ETHERSCAN_API_KEY")

    rpc_urls_str: Optional[str] = Field(default=None, alias="RPC_URLS")
    rpc_timeout: int = Field(default=30, alias="RPC_TIMEOUT")
    rpc_max_retries: int = Field(default=3, alias="RPC_MAX_RETRIES")
    rpc_rate_limit: float = Field(default=10.0, alias="RPC_RATE_LIMIT")

    database_url: PostgresDsn = Field(
        default="postgresql+psycopg://oio:oio@localhost:5432/oio",
        alias="DATABASE_URL",
    )
    sqlite_cache_path: Path = Field(
        default=Path("./.oio_cache.sqlite"),
        alias="SQLITE_CACHE_PATH",
    )

    default_block_range: int = Field(default=100_000, alias="DEFAULT_BLOCK_RANGE")
    max_transactions_sample: int = Field(default=10_000, alias="MAX_TX_SAMPLE")
    deep_analysis_threshold: int = Field(default=1_000, alias="DEEP_ANALYSIS_THRESHOLD")
    invariant_confidence_threshold: float = Field(default=0.95, alias="INV_CONFIDENCE")

    llm_model: str = Field(default="claude-sonnet-4-20250514", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=4096, alias="LLM_MAX_TOKENS")

    embedding_model: str = Field(default="nomic-embed-text", alias="EMBEDDING_MODEL")
    vector_dimension: int = Field(default=768, alias="VECTOR_DIMENSION")
    rag_top_k: int = Field(default=5, alias="RAG_TOP_K")

    output_dir: Path = Field(default=Path("./oio-output"), alias="OUTPUT_DIR")

    @property
    def rpc_urls(self) -> List[str]:
        if not self.rpc_urls_str:
            return []
        return [url.strip() for url in self.rpc_urls_str.split(",") if url.strip()]

    @field_validator("output_dir", "sqlite_cache_path", mode="before")
    @classmethod
    def parse_path(cls, v):
        if v is None:
            return None
        return Path(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()
