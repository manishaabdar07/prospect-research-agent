"""Stable-ish id helpers shared across stages.

company_id is a stable slug derived from the company name (spec: "stable
slug"), so re-ingesting the same company CSV twice resolves to the same
Company row instead of creating duplicates. prospect_id and finding_id are
random but prefixed for readability in logs/DB browsing.
"""
from __future__ import annotations

import re
import uuid


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "company"


def company_id_from_name(name: str) -> str:
    return f"co-{slugify(name)}"


def new_prospect_id() -> str:
    return f"pr-{uuid.uuid4().hex[:12]}"


def new_finding_id() -> str:
    return f"fd-{uuid.uuid4().hex[:12]}"
