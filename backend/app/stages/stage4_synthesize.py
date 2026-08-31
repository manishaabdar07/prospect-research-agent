"""Stage 4 - Synthesise: a SINGLE non-looping LLM call with a forced tool call.

Only ever invoked when hook_strength >= 2 -- the hook_strength < 2 check
happens in plain Python in the router BEFORE this module is imported/called
at all, so a disqualified prospect never reaches an LLM call here.

The `return_draft` tool's input_schema IS the OutreachDraft shape, and
tool_choice forces the model to call it, so the response is structured JSON
with no free-text parsing. After the call we validate in plain Python:
  - claims_used is non-empty when disqualify is False
  - every id in claims_used exists among that prospect's Finding rows
On failure we retry once with the validation error appended; on a second
failure we persist a best-effort draft flagged needs_human_review=True
rather than dropping it silently.
"""
from __future__ import annotations

import json

import anthropic
from sqlalchemy import select

from app.config import get_settings
from app.models import EmailPurpose, Finding, OutreachDraft, Prospect, ProspectStatus

SYSTEM_PROMPT = (
    "You write first-touch B2B outreach for Gunadhya, a company selling to "
    "Pune-area manufacturers. You will be given a prospect and a list of "
    "cited findings about them and their company. Write:\n"
    "1. connection_note: <=280 characters, no pitch, exactly one specific "
    "observation plus one reason for reaching out, grounded only in the "
    "findings given.\n"
    "2. email_sequence: exactly 3 EmailSteps following connect -> warm -> "
    "give-then-ask: steps 1 and 2 have purpose=GIVE, step 3 has purpose=ASK. "
    "send_after_days must be 0, 4, and 9 for steps 1, 2, 3 respectively.\n"
    "Every factual claim you make anywhere in the note or emails MUST "
    "correspond to a finding_id you list in claims_used. Never claim a "
    "shared connection, event, or prior contact that is not present in the "
    "findings. If the findings are too thin to write a grounded, honest "
    "draft, set disqualify=true and explain why in disqualify_reason instead "
    "of inventing content."
)

RETURN_DRAFT_TOOL = {
    "name": "return_draft",
    "description": "Return the structured outreach draft.",
    "input_schema": {
        "type": "object",
        "properties": {
            "connection_note": {"type": "string", "maxLength": 280},
            "email_sequence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "integer"},
                        "send_after_days": {"type": "integer"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                        "purpose": {"type": "string", "enum": ["GIVE", "ASK"]},
                    },
                    "required": ["step", "send_after_days", "subject", "body", "purpose"],
                },
            },
            "claims_used": {
                "type": "array",
                "items": {"type": "string"},
                "description": "finding_id strings this draft's claims are grounded in.",
            },
            "disqualify": {"type": "boolean"},
            "disqualify_reason": {"type": ["string", "null"]},
        },
        "required": ["connection_note", "email_sequence", "claims_used", "disqualify"],
    },
}


class SynthesisOutcome:
    def __init__(self, status: str, draft: OutreachDraft | None) -> None:
        self.status = status  # DONE | DISQUALIFIED | ERROR
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

        connection_note = draft_input.get("connection_note", "")
        if not connection_note or len(connection_note) > 280:
            errors.append("connection_note must be non-empty and <=280 characters")

        email_sequence = draft_input.get("email_sequence") or []
        if len(email_sequence) != 3:
            errors.append("email_sequence must contain exactly 3 steps")
        else:
            expected_days = [0, 4, 9]
            expected_purpose = [EmailPurpose.GIVE.value, EmailPurpose.GIVE.value, EmailPurpose.ASK.value]
            for i, step in enumerate(email_sequence):
                if step.get("send_after_days") != expected_days[i]:
                    errors.append(f"email_sequence[{i}].send_after_days should be {expected_days[i]}")
                if step.get("purpose") != expected_purpose[i]:
                    errors.append(f"email_sequence[{i}].purpose should be {expected_purpose[i]}")

    return errors


def synthesize_prospect(db, prospect: Prospect) -> SynthesisOutcome:
    settings = get_settings()

    findings = db.scalars(select(Finding).where(Finding.prospect_id == prospect.prospect_id)).all()
    valid_finding_ids = {f.finding_id for f in findings}

    user_prompt = (
        f"Prospect: {prospect.full_name}, {prospect.title_raw}\n"
        f"Findings:\n{_findings_prompt_block(findings)}\n\n"
        "Call return_draft now."
    )

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    draft_input: dict | None = None
    last_errors: list[str] = []

    for attempt in range(2):  # one initial call + one retry
        try:
            response = client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                tools=[RETURN_DRAFT_TOOL],
                tool_choice={ "type": "tool", "name": "return_draft"},
                messages=messages,
            )
        except Exception as exc:
            return SynthesisOutcome("ERROR", _persist_flagged(db, prospect, None, f"Anthropic API call failed: {exc}"))

        tool_block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
        if tool_block is None:
            last_errors = ["model did not return a tool_use block"]
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": "You must call return_draft. Please try again."})
            continue

        draft_input = tool_block.input if isinstance(tool_block.input, dict) else json.loads(tool_block.input)
        errors = _validate(draft_input, valid_finding_ids)
        if not errors:
            last_errors = []
            break

        last_errors = errors
        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": "Validation failed: " + "; ".join(errors) + ". Please call return_draft again with corrected values.",
                        "is_error": True,
                    }
                ],
            }
        )

    if draft_input is None:
        return SynthesisOutcome("ERROR", _persist_flagged(db, prospect, None, "model never returned a tool_use block after retry"))

    if last_errors:
        # Second failure: never silently drop -- persist best-effort, flagged.
        return SynthesisOutcome(
            "ERROR",
            _persist_flagged(db, prospect, draft_input, "; ".join(last_errors), valid_finding_ids),
        )

    if bool(draft_input.get("disqualify", False)):
        outcome_draft = _persist_draft(
            db,
            prospect,
            connection_note="",
            email_sequence=[],
            claims_used=[],
            disqualify=True,
            disqualify_reason=draft_input.get("disqualify_reason") or "Findings too thin for a grounded draft.",
            needs_human_review=False,
        )
        prospect.status = ProspectStatus.DISQUALIFIED
        db.commit()
        return SynthesisOutcome("DISQUALIFIED", outcome_draft)

    outcome_draft = _persist_draft(
        db,
        prospect,
        connection_note=draft_input.get("connection_note", ""),
        email_sequence=draft_input.get("email_sequence", []),
        claims_used=draft_input.get("claims_used", []),
        disqualify=False,
        disqualify_reason=None,
        needs_human_review=False,
    )
    prospect.status = ProspectStatus.SYNTHESIZED
    db.commit()
    return SynthesisOutcome("DONE", outcome_draft)


def _persist_draft(
    db,
    prospect: Prospect,
    *,
    connection_note: str,
    email_sequence: list,
    claims_used: list,
    disqualify: bool,
    disqualify_reason: str | None,
    needs_human_review: bool,
) -> OutreachDraft:
    existing = db.get(OutreachDraft, prospect.prospect_id)
    if existing is not None:
        db.delete(existing)
        db.flush()
    draft = OutreachDraft(
        prospect_id=prospect.prospect_id,
        connection_note=connection_note[:280],
        email_sequence=email_sequence,
        claims_used=claims_used,
        disqualify=disqualify,
        disqualify_reason=disqualify_reason,
        needs_human_review=needs_human_review,
    )
    db.add(draft)
    db.flush()
    return draft


def _persist_flagged(
    db,
    prospect: Prospect,
    draft_input: dict | None,
    error_note: str,
    valid_finding_ids: set[str] | None = None,
) -> OutreachDraft:
    valid_finding_ids = valid_finding_ids or set()
    draft_input = draft_input or {}
    claims_used = [c for c in (draft_input.get("claims_used") or []) if c in valid_finding_ids]
    draft = _persist_draft(
        db,
        prospect,
        connection_note=str(draft_input.get("connection_note", ""))[:280],
        email_sequence=draft_input.get("email_sequence") or [],
        claims_used=claims_used,
        disqualify=False,
        disqualify_reason=f"NEEDS HUMAN REVIEW: {error_note}",
        needs_human_review=True,
    )
    prospect.status = ProspectStatus.SYNTHESIZED
    db.commit()
    return draft
