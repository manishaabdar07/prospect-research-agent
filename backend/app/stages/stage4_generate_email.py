"""Stage 4 - Generate Email: a SINGLE non-looping LLM call with a forced tool call.

Only ever invoked when hook_strength >= 2 -- the hook_strength < 2 check
happens in plain Python in the router BEFORE this module is imported/called
at all, so a disqualified prospect never reaches an LLM call here.

The `return_email` tool's input_schema IS the EmailDraft shape (single
subject+body email -- no LinkedIn connection note, no multi-step drip
sequence), and tool_choice forces the model to call it, so the response is
structured JSON with no free-text parsing. After the call we validate in
plain Python:
  - claims_used is non-empty when disqualify is False
  - every id in claims_used exists among that prospect's Finding rows
  - subject/body are non-empty
On failure we retry once with the validation error appended; on a second
failure we persist a best-effort draft flagged needs_human_review=True
rather than dropping it silently. A hard failure (the API call itself raises,
or the model never returns usable content at all) is a system error, not a
business outcome -- that routes to ProspectStatus.ERROR with no draft
persisted, distinct from a model-judged DISQUALIFIED.
"""
from __future__ import annotations

import json
from datetime import datetime

import openai
from sqlalchemy import select

from app.agent.tools import _log
from app.config import get_settings
from app.llm_client import get_openai_client
from app.models import EmailDraft, Finding, Prospect, ProspectStatus

SYSTEM_PROMPT = (
    "You write a single first-touch outreach email for Gunadhya, a company "
    "selling to Pune-area manufacturers. You will be given a prospect and a "
    "list of cited findings about them and their company. Write:\n"
    "1. subject: a short, specific subject line grounded only in the findings "
    "given -- no generic sales-y phrasing.\n"
    "2. body: a concise first-touch email. No pitch-heavy language, no "
    "multiple asks -- one specific observation about the prospect/company "
    "plus one clear reason for reaching out, grounded only in the findings "
    "given.\n"
    "Every factual claim you make anywhere in subject or body MUST correspond "
    "to a finding_id you list in claims_used. Never invent or assume: company "
    "facts, person facts, events, relationships, prior communication, shared "
    "connections, or business problems that are not stated in the findings. "
    "If the findings are too thin to write a grounded, honest email, set "
    "disqualify=true and explain why in disqualify_reason instead of "
    "inventing content."
)

RETURN_EMAIL_TOOL = {
    "type": "function",
    "function": {
        "name": "return_email",
        "description": "Return the structured outreach email draft.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "maxLength": 500},
                "body": {"type": "string"},
                "claims_used": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "finding_id strings this email's claims are grounded in.",
                },
                "disqualify": {"type": "boolean"},
                "disqualify_reason": {"type": ["string", "null"]},
            },
            "required": ["subject", "body", "claims_used", "disqualify"],
        },
    },
}


class EmailGenerationOutcome:
    def __init__(self, status: str, draft: EmailDraft | None) -> None:
        self.status = status  # DONE | DISQUALIFIED | NEEDS_REVIEW | ERROR
        self.draft = draft


def _findings_prompt_block(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        lines.append(
            f"- finding_id={f.finding_id} | slot={f.slot.value if hasattr(f.slot, 'value') else f.slot} "
            f"| claim=\"{f.claim}\" | source_url={f.source_url} | confidence={f.confidence}"
        )
    return "\n".join(lines) if lines else "(no findings)"


def _validate(draft_input: dict, valid_finding_ids: set[str]) -> list[str]:
    errors: list[str] = []

    disqualify = bool(draft_input.get("disqualify", False))
    claims_used = draft_input.get("claims_used") or []
    if not isinstance(claims_used, list):
        errors.append("claims_used must be a list of finding_id strings")
        claims_used = []

    if not disqualify:
        if not claims_used:
            errors.append("claims_used must be non-empty when disqualify is false")
        unknown = [c for c in claims_used if c not in valid_finding_ids]
        if unknown:
            errors.append(f"claims_used references unknown finding_id(s): {unknown}")

        subject = draft_input.get("subject", "")
        if not subject or len(subject) > 500:
            errors.append("subject must be non-empty and <=500 characters")

        body = draft_input.get("body", "")
        if not body:
            errors.append("body must be non-empty")

    return errors


def generate_email(db, prospect: Prospect, client: openai.OpenAI | None = None) -> EmailGenerationOutcome:
    settings = get_settings()

    findings = db.scalars(select(Finding).where(Finding.prospect_id == prospect.prospect_id)).all()
    valid_finding_ids = {f.finding_id for f in findings}

    user_prompt = (
        f"Prospect: {prospect.full_name}, {prospect.title_raw}\n"
        f"Findings:\n{_findings_prompt_block(findings)}\n\n"
        "Call return_email now."
    )

    if client is None:
        client = get_openai_client()
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    draft_input: dict | None = None
    last_errors: list[str] = []

    for _attempt in range(2):  # one initial call + one retry
        try:
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                max_tokens=2000,
                tools=[RETURN_EMAIL_TOOL],
                tool_choice={"type": "function", "function": {"name": "return_email"}},
                messages=messages,
            )
        except Exception as exc:
            return EmailGenerationOutcome("ERROR", _mark_error(db, prospect, f"LLM API call failed: {exc}"))

        if response.usage is not None:
            _log(
                f"[agent] generate_email turn tokens: prompt={response.usage.prompt_tokens} "
                f"completion={response.usage.completion_tokens} total={response.usage.total_tokens}"
            )

        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        tool_call = tool_calls[0] if tool_calls else None
        if tool_call is None:
            last_errors = ["model did not return a tool call"]
            messages.append({"role": "assistant", "content": message.content})
            messages.append({"role": "user", "content": "You must call return_email. Please try again."})
            continue

        try:
            draft_input = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
        except (TypeError, ValueError):
            draft_input = {}
        errors = _validate(draft_input, valid_finding_ids)
        if not errors:
            last_errors = []
            break

        last_errors = errors
        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments},
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": "Validation failed: " + "; ".join(errors) + ". Please call return_email again with corrected values.",
            }
        )

    if draft_input is None:
        return EmailGenerationOutcome("ERROR", _mark_error(db, prospect, "model never returned a tool call after retry"))

    if last_errors:
        # Second failure: there IS content worth a human looking at -- never
        # silently drop it, persist best-effort and flag instead of erroring.
        draft = _persist_draft(
            db,
            prospect,
            subject=str(draft_input.get("subject", ""))[:500],
            body=str(draft_input.get("body", "")),
            claims_used=[c for c in (draft_input.get("claims_used") or []) if c in valid_finding_ids],
            disqualify=False,
            disqualify_reason="NEEDS HUMAN REVIEW: " + "; ".join(last_errors),
            needs_human_review=True,
        )
        prospect.status = ProspectStatus.EMAIL_DRAFTED
        db.commit()
        return EmailGenerationOutcome("NEEDS_REVIEW", draft)

    if bool(draft_input.get("disqualify", False)):
        draft = _persist_draft(
            db,
            prospect,
            subject="",
            body="",
            claims_used=[],
            disqualify=True,
            disqualify_reason=draft_input.get("disqualify_reason") or "Findings too thin for a grounded email.",
            needs_human_review=False,
        )
        prospect.status = ProspectStatus.DISQUALIFIED
        db.commit()
        return EmailGenerationOutcome("DISQUALIFIED", draft)

    draft = _persist_draft(
        db,
        prospect,
        subject=draft_input.get("subject", ""),
        body=draft_input.get("body", ""),
        claims_used=draft_input.get("claims_used", []),
        disqualify=False,
        disqualify_reason=None,
        needs_human_review=False,
    )
    prospect.status = ProspectStatus.EMAIL_DRAFTED
    db.commit()
    return EmailGenerationOutcome("DONE", draft)


def _persist_draft(
    db,
    prospect: Prospect,
    *,
    subject: str,
    body: str,
    claims_used: list,
    disqualify: bool,
    disqualify_reason: str | None,
    needs_human_review: bool,
) -> EmailDraft:
    existing = db.get(EmailDraft, prospect.prospect_id)
    if existing is not None:
        db.delete(existing)
        db.flush()
    draft = EmailDraft(
        prospect_id=prospect.prospect_id,
        subject=subject,
        body=body,
        claims_used=claims_used,
        disqualify=disqualify,
        disqualify_reason=disqualify_reason,
        needs_human_review=needs_human_review,
    )
    db.add(draft)
    db.flush()
    return draft


def _mark_error(db, prospect: Prospect, message: str) -> None:
    prospect.status = ProspectStatus.ERROR
    prospect.last_error = message
    prospect.last_error_at = datetime.utcnow()
    db.commit()
    return None
