"""Stage 3 - Research Agent: a hand-rolled OpenAI tool-calling loop.

No framework -- a plain while-loop calling client.chat.completions.create
with tools=[...] and handling tool_calls, per spec. This is the ONLY
LLM-driven loop in the system; Stage 4 is a single non-looping call.

Stop conditions (enforced here, whichever fires first):
  1. model calls submit_findings
  2. AGENT_MAX_TOOL_CALLS tool calls used
  3. wall-clock exceeds AGENT_WALL_CLOCK_SECONDS
  4. AGENT_MAX_CONSECUTIVE_ERRORS consecutive tool errors occur

On any non-submit_findings termination we still assemble a result with
terminal_reason=BUDGET_EXHAUSTED or ERROR and whatever findings were
recorded so far -- this function never raises for expected failure modes;
it always returns an AgentRunResult.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import openai

from app.agent.tools import TOOL_DEFS, AgentSession, RecordedFinding, _log, handle_tool_call
from app.config import get_settings
from app.llm_client import get_openai_client
from app.models import Company, Prospect

def _build_system_prompt(max_tool_calls: int) -> str:
    return (
        "You are researching a prospect for a first-touch outreach message. Find "
        "specific, verifiable, recent facts that would make a stranger's message "
        "worth reading. You are not writing the message. Fill five evidence slots: "
        "WHAT_THEY_MAKE, CHANGE_SIGNAL, TECH_OPS_SIGNAL, HR_SIGNAL, PERSON_SIGNAL. "
        "Rules: Record a finding only with a source URL you actually retrieved. "
        "Paraphrase - never copy sentences from a source. If you cannot find "
        "something, say so; do not infer, do not generalise from the industry, do "
        "not fill a slot with a guess. Concluding that there is no usable hook is "
        "a correct and valuable outcome; prefer it to a weak one. "
        "Call record_finding immediately after any fetch that gives you a "
        "specific, citable fact for a slot -- do this before your next search "
        "or fetch call, not after you've explored further leads. A partial set "
        "of solid findings beats a fuller picture you never wrote down. "
        "Never call fetch on a linkedin.com URL -- it is always blocked and "
        "will always fail; skip LinkedIn links in search results entirely and "
        "use a different source instead. Two failed tool calls in a row ends "
        "your session immediately with nothing recorded, so treat every fetch "
        "as a real attempt, not a guess -- don't fetch a URL you're inventing "
        "or unsure exists. "
        f"You have a budget of {max_tool_calls} tool calls total, across search, "
        "fetch, and record_finding combined. Spend them wisely, and leave enough "
        "in reserve to call submit_findings before the budget runs out."
    )


def _build_initial_prompt(prospect: Prospect, company: Company) -> str:
    place = company.city or ""
    title = prospect.title_raw or ""
    company_place = f"{company.name} {place}".strip()

    hints = [
        company_place,
        f"{company.name} careers",
        f"{company.name} jobs {place}".strip(),
        f"{company.name} expansion OR new plant OR investment",
        f"{company.name} IATF 16949 OR ISO certification",
        f'"{prospect.full_name}" {title} {company.name}'.strip(),
        f"{company.name} apprentice OR ITI OR contract workers",
    ]
    # domain is optional -- only add a site: search if one happens to be on
    # file; never guess one, since a wrong guess produces a dead-end query.
    if company.domain:
        hints.insert(0, f'"{company.name}" site:{company.domain}')

    hints_block = "\n".join(f"- {h}" for h in hints)
    person_line = f"Prospect: {prospect.full_name}" + (f", {title}" if title else "")
    return (
        f"{person_line}\n"
        f"Company: {company.name} ({place or 'location unknown'}, "
        f"industry: {company.industry_raw or 'unknown'}, "
        f"headcount: {company.headcount if company.headcount is not None else 'unknown'})\n\n"
        "Some suggested search queries to get started (use, adapt, or ignore as you see fit):\n"
        f"{hints_block}\n\n"
        "Research this prospect and their company, then call submit_findings when done."
    )


@dataclass
class AgentRunResult:
    findings: list[RecordedFinding] = field(default_factory=list)
    hook_strength: int = 0
    terminal_reason: str = "ERROR"
    agent_notes: str = ""
    tool_calls_used: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


def _tool_call_dict(tc) -> dict:
    """Shape one OpenAI tool_call object into the plain dict form required
    when echoing it back inside an assistant message."""
    return {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
    }


def _parse_tool_arguments(tc) -> dict:
    try:
        parsed = json.loads(tc.function.arguments) if tc.function.arguments else {}
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _compact_stale_fetch_result(msg: dict) -> None:
    """Replace a fetched page's full text with a short placeholder once the
    model has already had one full turn to act on it (the system prompt
    tells it to call record_finding right away, before its next search/
    fetch). Without this, every page fetched early in a session gets resent
    in full on every remaining turn -- the single biggest driver of token
    growth in a long research session. Safe to do: the citation-integrity
    check in agent/tools.py is enforced via `session.fetched_urls` (a plain
    Python set), not by the model re-reading old fetch results here, so
    compacting history has no effect on which sources can still be cited."""
    original_len = len(msg.get("content") or "")
    msg["content"] = (
        f"[fetched earlier -- {original_len} chars omitted here to save context. "
        "If you still need this page's text, call fetch on the same URL again.]"
    )


def run_research_agent(
    prospect: Prospect, company: Company, client: openai.OpenAI | None = None
) -> AgentRunResult:
    settings = get_settings()
    session = AgentSession()
    if client is None:
        client = get_openai_client()

    messages: list[dict] = [
        {"role": "system", "content": _build_system_prompt(settings.AGENT_MAX_TOOL_CALLS)},
        {"role": "user", "content": _build_initial_prompt(prospect, company)},
    ]
    _log(f"[agent] === START prospect={prospect.full_name!r} company={company.name!r} ===")
    start = time.monotonic()
    consecutive_errors = 0
    non_tool_turns = 0
    token_totals = {"prompt": 0, "completion": 0, "total": 0}
    # Two-stage delay so a fetch's content is compacted only *after* the model
    # has had one full turn to see and act on it -- not before. A fetch
    # executed during iteration N is appended to `messages` at the end of N;
    # the model first sees it when generating iteration N+1's response. So:
    #   iteration N:   this_turn_fetch_ids = {new fetches from N}
    #   end of N:      awaiting_first_view -> ready_to_compact (now seen once)
    #                  this_turn_fetch_ids -> awaiting_first_view (not yet seen)
    #   top of N+1:    compact ready_to_compact (safe: already seen once)
    fetch_ids_awaiting_first_view: set[str] = set()
    fetch_ids_ready_to_compact: set[str] = set()

    def assemble(terminal_reason: str, notes: str, hook_strength: int | None = None) -> AgentRunResult:
        if hook_strength is None:
            # The model never got to self-score via submit_findings (budget/
            # timeout/error exit). Don't silently discard real findings just
            # because the session didn't end cleanly: score conservatively
            # from what was actually recorded rather than defaulting to 0.
            # Capped at 2 (rubric's "one specific, verifiable fact") since
            # only the model can judge whether a finding clears the bar for
            # 3 ("plausibly connects to something the prospect's company does").
            hook_strength = 2 if session.findings else 0
        _log(
            f"[agent] DONE terminal_reason={terminal_reason} hook_strength={hook_strength} "
            f"tool_calls_used={session.tool_calls_used} findings_recorded={len(session.findings)} "
            f"tokens_prompt={token_totals['prompt']} tokens_completion={token_totals['completion']} "
            f"tokens_total={token_totals['total']}"
        )
        return AgentRunResult(
            findings=list(session.findings),
            hook_strength=hook_strength,
            terminal_reason=terminal_reason,
            agent_notes=notes,
            tool_calls_used=session.tool_calls_used,
            prompt_tokens=token_totals["prompt"],
            completion_tokens=token_totals["completion"],
            total_tokens=token_totals["total"],
        )

    while True:
        elapsed = time.monotonic() - start
        if elapsed > settings.AGENT_WALL_CLOCK_SECONDS:
            return assemble("BUDGET_EXHAUSTED", "Stopped: wall-clock budget exceeded.")
        if session.tool_calls_used >= settings.AGENT_MAX_TOOL_CALLS:
            return assemble("BUDGET_EXHAUSTED", "Stopped: tool-call budget exhausted.")

        if fetch_ids_ready_to_compact:
            for m in messages:
                if m.get("role") == "tool" and m.get("tool_call_id") in fetch_ids_ready_to_compact:
                    _compact_stale_fetch_result(m)
            fetch_ids_ready_to_compact = set()

        try:
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                max_tokens=2000,
                tools=TOOL_DEFS,
                messages=messages,
            )
        except Exception as exc:
            return assemble("ERROR", f"Stopped: LLM API call failed: {exc}")

        if response.usage is not None:
            token_totals["prompt"] += response.usage.prompt_tokens
            token_totals["completion"] += response.usage.completion_tokens
            token_totals["total"] += response.usage.total_tokens
            _log(
                f"[agent] turn tokens: prompt={response.usage.prompt_tokens} "
                f"completion={response.usage.completion_tokens} total={response.usage.total_tokens}"
            )

        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        if not tool_calls:
            non_tool_turns += 1
            if non_tool_turns >= 2:
                return assemble("ERROR", "Stopped: model did not call submit_findings after repeated nudges.")
            messages.append({"role": "assistant", "content": message.content})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Please continue using the available tools (search, fetch, "
                        "record_finding), or call submit_findings to end the session."
                    ),
                }
            )
            continue

        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [_tool_call_dict(tc) for tc in tool_calls],
            }
        )

        tool_result_messages: list[dict] = []
        submitted: AgentRunResult | None = None
        this_turn_fetch_ids: set[str] = set()

        for tc in tool_calls:
            tool_input = _parse_tool_arguments(tc)

            if session.tool_calls_used >= settings.AGENT_MAX_TOOL_CALLS:
                tool_result_messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": "error: tool-call budget exhausted"}
                )
                continue

            session.tool_calls_used += 1

            if tc.function.name == "submit_findings":
                hook_strength_raw = tool_input.get("hook_strength", 0)
                try:
                    hook_strength = int(hook_strength_raw)
                except (TypeError, ValueError):
                    hook_strength = 0
                hook_strength = max(0, min(3, hook_strength))
                terminal_reason = tool_input.get("terminal_reason", "NO_HOOK")
                if terminal_reason not in ("SUFFICIENT", "NO_HOOK"):
                    terminal_reason = "NO_HOOK"
                notes = str(tool_input.get("notes", ""))
                submitted = assemble(terminal_reason, notes, hook_strength)
                tool_result_messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": "Findings submitted."}
                )
                continue

            result_text, is_error = handle_tool_call(session, tc.function.name, tool_input)
            tool_result_messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})

            if tc.function.name == "fetch" and not is_error:
                this_turn_fetch_ids.add(tc.id)

            is_linkedin_rejection = (
                tc.function.name == "fetch" and "linkedin.com" in str(tool_input.get("url", "")).lower()
            )
            if is_linkedin_rejection:
                # A deterministic, by-design policy rejection (see
                # fetch_util.py), not a genuine execution failure -- don't let
                # the model spending a call on a forbidden URL count toward
                # the consecutive-error safety valve alongside real failures
                # (timeouts, 404s, etc). The model still sees the rejection in
                # its own tool result and should not repeat it.
                pass
            elif is_error:
                consecutive_errors += 1
            else:
                consecutive_errors = 0

            if consecutive_errors >= settings.AGENT_MAX_CONSECUTIVE_ERRORS:
                # Fill a tool result for any remaining calls in this batch so
                # every tool_call_id gets a reply, then stop.
                remaining = tool_calls[tool_calls.index(tc) + 1 :]
                for rem in remaining:
                    tool_result_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": rem.id,
                            "content": "error: session terminated due to repeated tool errors",
                        }
                    )
                return assemble("ERROR", "Stopped: too many consecutive tool errors.")

        if submitted is not None:
            return submitted

        non_tool_turns = 0
        messages.extend(tool_result_messages)
        fetch_ids_ready_to_compact = fetch_ids_awaiting_first_view
        fetch_ids_awaiting_first_view = this_turn_fetch_ids
