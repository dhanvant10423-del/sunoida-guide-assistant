"""Validated application settings loaded from the project-root .env file.

Environment variables take priority over .env values. Relative data paths are
resolved from the project root, independent of the terminal's current folder.
"""

from ipaddress import IPv4Address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        env_prefix="SUNOIDA_",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "Sunoida User Guide Assistant"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    port_fallback_count: int = Field(default=10, ge=0, le=20)
    open_browser: bool = True
    log_level: Literal["critical", "error", "warning", "info", "debug", "trace"] = "info"

    ollama_url: str = "http://127.0.0.1:11434"
    ollama_timeout: float = Field(default=180, ge=1, le=900)
    chat_model: str = Field(default="qwen2.5:0.5b", min_length=1)
    vision_model: str = Field(default="qwen3-vl:2b", min_length=1)
    embed_model: str = Field(default="nomic-embed-text:v1.5", min_length=1)
    temperature: float = Field(default=0.1, ge=0, le=1)
    context_window: int = Field(default=4096, ge=1024, le=32768)
    max_response_tokens: int = Field(default=450, ge=32, le=4096)

    history_max_turns: int = Field(default=4, ge=1, le=10)
    history_max_chars: int = Field(default=5000, ge=1000, le=12000)
    history_ttl_seconds: int = Field(default=1800, ge=60, le=86400)
    history_max_sessions: int = Field(default=100, ge=1, le=1000)

    retrieval_top_k: int = Field(default=4, ge=1, le=10)
    min_similarity: float = Field(default=0.67, ge=0, le=1, allow_inf_nan=False)
    collection_name: str = Field(default="sunoida_guides_nomic_v15", min_length=1)
    docs_dir: Path = Path("backend/docs")
    db_dir: Path = Path("backend/chroma_db")
    cache_dir: Path = Path("backend/.page_cache")

    @field_validator("host")
    @classmethod
    def validate_host(cls, value):
        IPv4Address(value)
        return value

    @field_validator("ollama_url")
    @classmethod
    def validate_ollama_url(cls, value):
        parts = urlsplit(value)
        _ = parts.port  # Reject malformed or out-of-range ports.
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("Ollama URL must be an HTTP(S) address without credentials")
        if parts.path not in {"", "/"} or parts.query or parts.fragment:
            raise ValueError("Ollama URL must contain only the service address")
        return value.rstrip("/")

    @field_validator("docs_dir", "db_dir", "cache_dir")
    @classmethod
    def resolve_project_path(cls, value):
        expanded = value.expanduser()
        return (expanded if expanded.is_absolute() else PROJECT_DIR / expanded).resolve()

    @model_validator(mode="after")
    def validate_port_range(self):
        if self.port + self.port_fallback_count > 65535:
            raise ValueError("The starting port plus fallback count must not exceed 65535")
        if self.max_response_tokens >= self.context_window:
            raise ValueError("Response token limit must be smaller than the context window")
        return self


settings = Settings()
