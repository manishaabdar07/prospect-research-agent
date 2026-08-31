"""Stage 3 - Research Agent: a hand-rolled Anthropic Messages API tool-use loop.

No framework -- a plain while-loop calling client.messages.create with
tools=[...] and handling tool_use content blocks, per spec. This is the
ONLY LLM-driven loop in the system; Stage 4 is a single non-looping call.

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

import time
from dataclasses import dataclass, field

import anthropic

from app.agent.tools import TOOL_DEFS, AgentSession, RecordedFinding, handle_tool_call
from app.config import get_settings
from app.models import Company, Prospect

SYSTEM_PROMPT = (
    "You are researching a prospect for a first-touch outreach message. Find "
    "specific, verifiable, recent facts that would make a stranger's message "
    "worth reading. You are not writing the message. Fill five evidence slots: "
    "WHAT_THEY_MAKE, CHANGE_SIGNAL, TECH_OPS_SIGNAL, HR_SIGNAL, PERSON_SIGNAL. "
    "Rules: Record a finding only with a source URL you actually retrieved. "
    "Paraphrase - never copy sentences from a source. If you cannot find "
    "something, say so; do not infer, do not generalise from the industry, do "
    "not fill a slot with a guess. Concluding that there is no usable hook is "
    "a correct and valuable outcome; prefer it to a weak one. You have a "
    "budget of 12 tool calls. Spend them wisely."
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


def run_research_agent(prospect: Prospect, company: Company) -> AgentRunResult:
    settings = get_settings()
    session = AgentSession()
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    messages: list[dict] = [{"role": "user", "content": _build_initial_prompt(prospect, company)}]
    start = time.monotonic()
    consecutive_errors = 0
    non_tool_turns = 0

    def assemble(terminal_reason: str, notes: str, hook_strength: int = 0) -> AgentRunResult:
        return AgentRunResult(
            findings=list(session.findings),
            hook_strength=hook_strength,
            terminal_reason=terminal_reason,
            agent_notes=notes,
            tool_calls_used=session.tool_calls_used,
        )

    while True:
        elapsed = time.monotonic() - start
        if elapsed > settings.AGENT_WALL_CLOCK_SECONDS:
            return assemble("BUDGET_EXHAUSTED", "Stopped: wall-clock budget exceeded.")
        if session.tool_calls_used >= settings.AGENT_MAX_TOOL_CALLS:
            return assemble("BUDGET_EXHAUSTED", "Stopped: tool-call budget exhausted.")

        try:
            response = client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFS,
                messages=messages,
            )
        except Exception as exc:
            return assemble("ERROR", f"Stopped: Anthropic API call failed: {exc}")

        tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

        if not tool_use_blocks:
            non_tool_turns += 1
            if non_tool_turns >= 2:
                return assemble("ERROR", "Stopped: model did not call submit_findings after repeated nudges.")
            messages.append({"role": "assistant", "content": response.content})
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

        messages.append({"role": "assistant", "content": response.content})

        tool_results: list[dict] = []
        submitted: AgentRunResult | None = None

        for block in tool_use_blocks:
            if session.tool_calls_used >= settings.AGENT_MAX_TOOL_CALLS:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "error: tool-call budget exhausted",
                        "is_error": True,
                    }
                )
                continue

            session.tool_calls_used += 1

            if block.name == "submit_findings":
                hook_strength_raw = block.input.get("hook_strength", 0)
                try:
                    hook_strength = int(hook_strength_raw)
                except (TypeError, ValueError):
                    hook_strength = 0
                hook_strength = max(0, min(3, hook_strength))
                terminal_reason = block.input.get("terminal_reason", "NO_HOOK")
                if terminal_reason not in ("SUFFICIENT", "NO_HOOK"):
                    terminal_reason = "NO_HOOK"
                notes = str(block.input.get("notes", ""))
                submitted = assemble(terminal_reason, notes, hook_strength)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Findings submitted.",
                    }
                )
                continue

            result_text, is_error = handle_tool_call(session, block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                    "is_error": is_error,
                }
            )
            if is_error:
                consecutive_errors += 1
            else:
                consecutive_errors = 0

            if consecutive_errors >= settings.AGENT_MAX_CONSECUTIVE_ERRORS:
                # Fill tool_result for any remaining blocks in this batch so the
                # message stays well-formed, then stop.
                remaining = tool_use_blocks[tool_use_blocks.index(block) + 1 :]
                for rem in remaining:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": rem.id,
                            "content": "error: session terminated due to repeated tool errors",
                            "is_error": True,
                        }
                    )
                return assemble("ERROR", "Stopped: too many consecutive tool errors.")

        if submitted is not None:
            return submitted

        non_tool_turns = 0
        messages.append({"role": "user", "content": tool_results})
