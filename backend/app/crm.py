"""Stage 6 - Load.

Deviation from the spec (documented here and in the README): the spec
suggests SQLite for the CRM adapter's own storage, but this whole system
already runs on Postgres, so PostgresCRMAdapter just upserts into the same
companies/prospects tables and writes a crm_tasks row -- this IS the CRM for
v1. There is no external CRM integration; the Protocol is kept exactly as
specified so a real adapter (HubSpot, Zoho, etc.) can be dropped in later
without touching calling code.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol

from sqlalchemy.orm import Session

from app.models import Company, CRMTask, Prospect


class CRMAdapter(Protocol):
    def upsert_company(self, c: Company) -> str: ...
    def upsert_contact(self, p: Prospect, company_ref: str) -> str: ...
    def create_task(self, contact_ref: str, title: str, due: date) -> None: ...


class PostgresCRMAdapter:
    """v1 CRM: the app's own Postgres tables ARE the CRM."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert_company(self, c: Company) -> str:
        existing = self.db.get(Company, c.company_id)
        if existing is None:
            self.db.add(c)
        else:
            existing.name = c.name
            existing.domain = c.domain
            existing.headcount = c.headcount
            existing.city = c.city
            existing.industry_raw = c.industry_raw
        self.db.commit()
        return c.company_id

    def upsert_contact(self, p: Prospect, company_ref: str) -> str:
        existing = self.db.get(Prospect, p.prospect_id)
        if existing is None:
            p.company_id = company_ref
            self.db.add(p)
        else:
            existing.full_name = p.full_name
            existing.title_raw = p.title_raw
            existing.email = p.email
            existing.linkedin_url = p.linkedin_url
            existing.company_id = company_ref
        self.db.commit()
        return p.prospect_id

    def create_task(self, contact_ref: str, title: str, due: date) -> None:
        task = CRMTask(contact_ref=contact_ref, title=title, due=due)
        self.db.add(task)
        self.db.commit()
