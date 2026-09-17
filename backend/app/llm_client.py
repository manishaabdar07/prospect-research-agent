"""OpenAI client construction, shared by Stage 3 (research agent loop) and
Stage 4 (email generation) -- the only two LLM call sites in the system.

Kept as a thin factory, not a bigger wrapper: call sites still use the
official openai SDK's own request/response objects directly (same pattern as
app/email_service.py::get_email_service() for the SMTP client).
"""
from __future__ import annotations

import openai

from app.config import get_settings


def get_openai_client() -> openai.OpenAI:
    settings = get_settings()
    return openai.OpenAI(api_key=settings.OPENAI_API_KEY)
