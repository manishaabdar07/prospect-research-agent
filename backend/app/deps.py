"""Shared FastAPI dependencies / helpers used across routers."""
from __future__ import annotations

from fastapi import HTTPException

from app.config import get_settings


def require_llm_configured() -> None:
    """Endpoints that call the LLM must fail cleanly, not crash, when no key is set."""
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="LLM not configured, set ANTHROPIC_API_KEY")
