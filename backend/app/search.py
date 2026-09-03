"""Pluggable search provider.

The spec is explicit that the search provider will change, so everything
outside this module talks to the single `search(query) -> list[SearchResult]`
function and never imports a provider directly. Provider is selected via
SEARCH_PROVIDER env var; "mock" (default) needs no API key and lets the app
run out of the box, "brave" calls the real Brave Search API.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx
from lxml import html as lxml_html

from app.config import get_settings


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


def _mock_search(query: str) -> list[SearchResult]:
    """Default provider. Returns an empty result set (no API key required).

    Kept deliberately empty rather than fabricating fake URLs/snippets --
    fabricated search results would tempt the agent to "fetch" fake pages,
    and this whole design exists to keep hallucination out of the loop.
    A canned non-empty response can be swapped in for local UI testing if
    needed, but empty-by-default is the safer choice for a shipped default.
    """
    return []


def _brave_search(query: str, count: int = 8) -> list[SearchResult]:
    settings = get_settings()
    if not settings.BRAVE_API_KEY:
        return []
    try:
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": count},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": settings.BRAVE_API_KEY,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results: list[SearchResult] = []
    for item in data.get("web", {}).get("results", []):
        results.append(
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
            )
        )
    return results


def _duckduckgo_search(query: str, count: int = 8) -> list[SearchResult]:
    """No-signup fallback provider: scrapes DuckDuckGo's plain-HTML results page
    (html.duckduckgo.com -- the non-JS endpoint, returns direct result URLs).

    DuckDuckGo has no free public search API, so this is best-effort HTML
    scraping rather than a documented API contract; like the other providers
    it fails open (returns []) on any network/parsing error instead of raising.
    """
    try:
        resp = httpx.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; ProspectResearchAgent/1.0)"},
            timeout=10.0,
        )
        resp.raise_for_status()
        tree = lxml_html.fromstring(resp.text)
    except Exception:
        return []

    results: list[SearchResult] = []
    for link in tree.xpath('//a[@class="result__a"]'):
        href = link.get("href", "").strip()
        title = link.text_content().strip()
        if not href:
            continue
        snippet_nodes = link.xpath(
            './ancestor::div[contains(@class, "result__body")][1]//a[@class="result__snippet"]'
        )
        snippet = snippet_nodes[0].text_content().strip() if snippet_nodes else ""
        results.append(SearchResult(title=title, url=href, snippet=snippet))
        if len(results) >= count:
            break
    return results


_PROVIDERS = {
    "mock": _mock_search,
    "brave": _brave_search,
    "duckduckgo": _duckduckgo_search,
}


def search(query: str) -> list[SearchResult]:
    settings = get_settings()
    provider = _PROVIDERS.get(settings.SEARCH_PROVIDER, _mock_search)
    return provider(query)
