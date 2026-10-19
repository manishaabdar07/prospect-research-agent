"""Shared FastAPI dependencies / helpers used across routers."""
from __future__ import annotations

from fastapi import HTTPException

from app.config import get_settings


def require_llm_configured() -> None:
    """Endpoints that call the LLM must fail cleanly, not crash, when no key is set."""
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="LLM not configured, set OPENAI_API_KEY")


def require_email_configured() -> None:
    """Endpoints that send email must fail cleanly, not crash, when SMTP isn't set."""
    settings = get_settings()
    if not settings.EMAIL_HOST or not settings.EMAIL_FROM:
        raise HTTPException(status_code=503, detail="Email not configured, set EMAIL_HOST/EMAIL_FROM")
