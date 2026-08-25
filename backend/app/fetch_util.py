"""Public-page fetch + readable-text extraction used by the Stage 3 `fetch` tool.

No browser automation, no auth -- plain httpx GET against public URLs, with
trafilatura pulling readable article text out of the HTML. Truncated to
~4000 tokens (~16000 chars) per the spec. LinkedIn/authenticated platforms
are never fetched; the agent only has this one fetch tool and it is a plain
GET, so there is no code path that could authenticate anywhere.
"""
from __future__ import annotations

import httpx

from app.config import get_settings

try:
    import trafilatura
except ImportError:  # pragma: no cover - trafilatura is a hard requirement, guarded defensively
    trafilatura = None


class FetchError(Exception):
    pass


def fetch_and_extract(url: str) -> str:
    """Fetch `url` and return truncated readable text, or raise FetchError."""
    settings = get_settings()

    if not url.lower().startswith(("http://", "https://")):
        raise FetchError("only http(s) URLs may be fetched")

    if "linkedin.com" in url.lower():
        raise FetchError("linkedin_url is stored as opaque data and is never fetched")

    try:
        resp = httpx.get(
            url,
            timeout=settings.FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "ProspectResearchAgent/1.0 (+internal research tool)"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise FetchError(f"fetch failed: {exc}") from exc

    html = resp.text
    text = None
    if trafilatura is not None:
        try:
            text = trafilatura.extract(html, include_comments=False, include_tables=False)
        except Exception:
            text = None

    if not text:
        # Fallback: crude tag strip so a fetch never comes back totally empty
        # just because trafilatura couldn't find an "article" on the page.
        import re

        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()

    return text[: settings.FETCH_MAX_CHARS]
