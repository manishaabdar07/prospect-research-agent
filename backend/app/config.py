"""Application configuration, read from environment / .env via pydantic-settings.

All values have safe local-dev defaults so the app boots with zero configuration
(mock search provider, sqlite fallback is NOT used by default -- see DATABASE_URL --
but the app must not crash at import time just because Postgres isn't reachable yet;
that failure only surfaces when a DB session is actually used).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database ---
    # Matches the root docker-compose.yml service credentials exactly
    # (user=prospect, password=prospect, db=prospect_research).
    DATABASE_URL: str = "postgresql://prospect:prospect@localhost:5432/prospect_research"

    # --- Anthropic / LLM ---
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-sonnet-5"

    # --- Search provider ---
    SEARCH_PROVIDER: str = "mock"  # "mock" | "brave"
    BRAVE_API_KEY: str | None = None

    # --- CORS ---
    CORS_ORIGINS: str = "http://localhost:5173"

    # --- Stage 3 agent budget knobs ---
    AGENT_MAX_TOOL_CALLS: int = 12
    AGENT_WALL_CLOCK_SECONDS: int = 90
    AGENT_MAX_CONSECUTIVE_ERRORS: int = 2

    # --- Qualification knobs (Stage 2) ---
    QUALIFY_BATCH_CAP: int = 20
    QUALIFY_HEADCOUNT_MIN: int = 10
    QUALIFY_HEADCOUNT_MAX: int = 200

    # --- Fetch / extraction ---
    FETCH_TIMEOUT_SECONDS: float = 15.0
    FETCH_MAX_CHARS: int = 16000  # ~4000 tokens

    # --- Storage ---
    PDF_DIR: Path = BACKEND_DIR / "data" / "pdfs"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
