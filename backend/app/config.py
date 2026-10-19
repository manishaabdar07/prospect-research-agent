"""Application configuration, read from environment / .env via pydantic-settings.

All values have safe local-dev defaults so the app boots with zero configuration
(mock search provider, sqlite fallback is NOT used by default -- see DATABASE_URL --
but the app must not crash at import time just because Postgres isn't reachable yet;
that failure only surfaces when a DB session is actually used).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database ---
    # Matches the root docker-compose.yml service credentials exactly
    # (user=prospect, password=prospect, db=prospect_research).
    DATABASE_URL: str = "postgresql://prospect:prospect@localhost:5432/prospect_research"

    # --- OpenAI / LLM ---
    # gpt-4o supports tool/function calling; override via .env for a
    # different model. Note: an o-series/reasoning model would need
    # max_completion_tokens instead of max_tokens in the API calls.
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o"

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

    # --- Email sending (Stage 6) ---
    # Generic SMTP only for v1 -- no third-party provider SDK. Leave EMAIL_HOST
    # unset to run the app without sending capability; /send-email returns a
    # clean 503 until it's configured (see app/deps.py::require_email_configured).
    EMAIL_PROVIDER: str = "smtp"
    EMAIL_HOST: str | None = None
    EMAIL_PORT: int = 587
    EMAIL_USERNAME: str | None = None
    EMAIL_PASSWORD: str | None = None
    EMAIL_FROM: str | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
