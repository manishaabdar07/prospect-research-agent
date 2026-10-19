"""Stage 3 agent tool schemas + handlers.

THE SINGLE MOST IMPORTANT RULE in this whole system lives here:
`record_finding` MUST reject (tool_result with is_error=True, never a raised
exception / crash) any source_url that was not fetched via the `fetch` tool
earlier in that same agent session. This is enforced by checking membership
in `session.fetched_urls`, a per-run set populated only by successful `fetch`
calls. This is what stops the agent from hallucinating citations -- it is
validated here in code, not merely requested in the prompt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.fetch_util import FetchError, fetch_and_extract
from app.ids import new_finding_id
from app.search import search as run_search

# Diagnostic trace: appends one line per tool call to a plain file, so a real
# run's behavior (what it searched/fetched/recorded, and why it stopped) can
# be read back regardless of which terminal/process is running the server.
# This has repeatedly been the only way to root-cause "research came back
# empty" reports (e.g. the agent exploring extensively but never calling
# record_finding, or tripping the consecutive-error stop on a LinkedIn URL).
_DEBUG_LOG = Path(__file__).resolve().parent.parent.parent / "data" / "agent_debug.log"


def _log(msg: str) -> None:
    print(msg, flush=True)
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


VALID_SLOTS = {
    "WHAT_THEY_MAKE",
    "CHANGE_SIGNAL",
    "TECH_OPS_SIGNAL",
    "HR_SIGNAL",
    "PERSON_SIGNAL",
}


@dataclass
class RecordedFinding:
    finding_id: str
    slot: str
    claim: str
    source_url: str
    retrieved_at: datetime
    confidence: float


@dataclass
class AgentSession:
    """Per-run mutable state for one Stage 3 research session."""

    fetched_urls: set[str] = field(default_factory=set)
    findings: list[RecordedFinding] = field(default_factory=list)
    tool_calls_used: int = 0


# --------------------------------------------------------------------------
# Tool schemas (OpenAI Chat Completions function-calling format)
# --------------------------------------------------------------------------

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the public web. Returns a list of {title, url, snippet}.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The search query."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch",
            "description": (
                "Fetch a public URL and return its readable extracted text (truncated to "
                "roughly 4000 tokens). Only public pages -- never fetch linkedin.com URLs. "
                "You must fetch a URL with this tool BEFORE you can cite it in record_finding."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "The URL to fetch."}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_finding",
            "description": (
                "Record one atomic evidence finding into an evidence slot. source_url MUST "
                "be a URL you already fetched with the fetch tool in this same session -- "
                "citing a URL you have not fetched will be rejected."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slot": {
                        "type": "string",
                        "enum": sorted(VALID_SLOTS),
                        "description": "Which evidence slot this finding fills.",
                    },
                    "claim": {
                        "type": "string",
                        "description": "Your own paraphrase of the fact, <=30 words. Never copy sentences from the source.",
                    },
                    "source_url": {
                        "type": "string",
                        "description": "The URL you fetched that supports this claim.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Your confidence in this finding, 0.0-1.0.",
                    },
                },
                "required": ["slot", "claim", "source_url", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_findings",
            "description": (
                "End the research session and submit your overall assessment. Call this when "
                "you have filled the slots you can, or when you have concluded there is no "
                "usable hook -- concluding 'no hook' is a correct and valuable outcome."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hook_strength": {
                        "type": "integer",
                        "description": "0-3: how strong is the outreach hook based on findings so far.",
                    },
                    "terminal_reason": {
                        "type": "string",
                        "enum": ["SUFFICIENT", "NO_HOOK"],
                        "description": "SUFFICIENT if you found enough to work with, NO_HOOK if you concluded there is no usable hook.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "What was tried, what could and could not be found.",
                    },
                },
                "required": ["hook_strength", "terminal_reason", "notes"],
            },
        },
    },
]


class SubmitFindingsSignal(Exception):
    """Raised internally by handle_tool_call to unwind the loop on submit_findings."""

    def __init__(self, hook_strength: int, terminal_reason: str, notes: str) -> None:
        self.hook_strength = hook_strength
        self.terminal_reason = terminal_reason
        self.notes = notes
        super().__init__("submit_findings")


def handle_tool_call(session: AgentSession, tool_name: str, tool_input: dict) -> tuple[str, bool]:
    """Execute one tool call. Returns (result_text, is_error).

    Never raises for expected failure modes (bad URL, unfetched citation,
    etc) -- those come back as (message, True) tool_result errors so the
    model can see and correct its mistake, per spec ("return a tool-result
    error back to the model, not raise/crash").
    """
    if tool_name == "search":
        query = str(tool_input.get("query", "")).strip()
        if not query:
            return "error: query must not be empty", True
        try:
            results = run_search(query)
        except Exception as exc:
            _log(f"[agent] search {query!r} -> ERROR: {exc}")
            return f"error: search failed: {exc}", True
        _log(f"[agent] search {query!r} -> {len(results)} result(s)")
        if not results:
            return "No results found for this query.", False
        lines = [f"- {r.title} | {r.url} | {r.snippet}" for r in results]
        return "\n".join(lines), False

    if tool_name == "fetch":
        url = str(tool_input.get("url", "")).strip()
        if not url:
            return "error: url must not be empty", True
        try:
            text = fetch_and_extract(url)
        except FetchError as exc:
            _log(f"[agent] fetch {url!r} -> ERROR: {exc}")
            return f"error: {exc}", True
        except Exception as exc:
            _log(f"[agent] fetch {url!r} -> UNEXPECTED ERROR: {exc}")
            return f"error: unexpected fetch failure: {exc}", True
        session.fetched_urls.add(url)
        _log(f"[agent] fetch {url!r} -> OK, {len(text)} chars")
        return text, False

    if tool_name == "record_finding":
        slot = str(tool_input.get("slot", "")).strip()
        claim = str(tool_input.get("claim", "")).strip()
        source_url = str(tool_input.get("source_url", "")).strip()
        try:
            confidence = float(tool_input.get("confidence", 0.0))
        except (TypeError, ValueError):
            return "error: confidence must be a number between 0.0 and 1.0", True

        if slot not in VALID_SLOTS:
            _log(f"[agent] record_finding REJECTED (bad slot {slot!r})")
            return f"error: slot must be one of {sorted(VALID_SLOTS)}", True
        if not claim:
            _log("[agent] record_finding REJECTED (empty claim)")
            return "error: claim must not be empty", True
        if len(claim.split()) > 40:
            # Soft cap per spec ("<=30 words, don't hard-fail on word count"):
            # we still don't hard-fail here, just nudge -- but 40+ words is
            # clearly not a paraphrase anymore, so this is where we draw the
            # line between "a little long" (accepted) and "not a paraphrase"
            # (rejected, ask the model to tighten it).
            _log(f"[agent] record_finding REJECTED (claim too long, {len(claim.split())} words)")
            return "error: claim is too long -- paraphrase in <=30 words", True
        if not (0.0 <= confidence <= 1.0):
            _log(f"[agent] record_finding REJECTED (confidence {confidence} out of range)")
            return "error: confidence must be between 0.0 and 1.0", True

        # THE SINGLE MOST IMPORTANT RULE.
        if source_url not in session.fetched_urls:
            _log(f"[agent] record_finding REJECTED (source_url {source_url!r} not fetched this session; fetched so far: {sorted(session.fetched_urls)})")
            return (
                "error: source_url has not been fetched in this session. "
                "You must call fetch(url) on this URL before you can cite it in record_finding.",
                True,
            )

        _log(f"[agent] record_finding OK: slot={slot} source_url={source_url!r}")
        session.findings.append(
            RecordedFinding(
                finding_id=new_finding_id(),
                slot=slot,
                claim=claim,
                source_url=source_url,
                retrieved_at=datetime.utcnow(),
                confidence=confidence,
            )
        )
        return f"Recorded finding for slot {slot}.", False

    return f"error: unknown tool '{tool_name}'", True
