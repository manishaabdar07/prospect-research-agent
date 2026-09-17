"""email workflow overhaul: drop PDF/review, add email_drafts + qualification/error tracking

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-15

Replaces the PDF-review pipeline tail (Stage 5 render + Stage 6 approve/edit/
reject review queue) with a single-email generate/edit/send flow, and fixes
Stage 2 Qualify silently leaving failing prospects at INGESTED forever with no
recorded reason.

Hand-written, mirroring app/models.py exactly (see 0001_initial.py for why:
no live Postgres to autogenerate against in this environment).

Data note: this is a breaking schema change with no principled mapping from
the old RENDERED/APPROVED/EDITED/REJECTED statuses (a PDF-review workflow that
no longer exists) onto the new status set. Truncate prospects-dependent tables
and re-ingest rather than trying to carry old rows forward -- see README.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Sized off the longest new value, "RESEARCH_COMPLETED" (19 chars), with
# headroom -- matches how SQLAlchemy's Enum(native_enum=False) would size a
# freshly created column.
PROSPECT_STATUS = sa.Enum(
    "INGESTED",
    "QUALIFIED",
    "DISQUALIFIED",
    "RESEARCH_PENDING",
    "RESEARCHING",
    "RESEARCH_COMPLETED",
    "EMAIL_DRAFTED",
    "EMAIL_SENT",
    "ERROR",
    name="prospect_status",
    native_enum=False,
    length=32,
)
EMAIL_DRAFT_STATUS = sa.Enum("DRAFTED", "SENT", name="email_draft_status", native_enum=False)


def upgrade() -> None:
    # --- prospects: drop PDF columns, widen+repoint status, add reason/error tracking ---
    op.drop_column("prospects", "pdf_path")
    op.drop_column("prospects", "pdf_generated_at")
    op.alter_column("prospects", "status", type_=PROSPECT_STATUS, existing_type=sa.String(12))
    op.add_column("prospects", sa.Column("qualification_reason", sa.String(500), nullable=True))
    op.add_column("prospects", sa.Column("qualified_at", sa.DateTime, nullable=True))
    op.add_column("prospects", sa.Column("last_error", sa.Text, nullable=True))
    op.add_column("prospects", sa.Column("last_error_at", sa.DateTime, nullable=True))

    # --- remove the PDF-review-era tables ---
    op.drop_table("review_actions")
    op.drop_table("outreach_drafts")

    # --- new Stage 4 output table ---
    op.create_table(
        "email_drafts",
        sa.Column("prospect_id", sa.String(64), sa.ForeignKey("prospects.prospect_id"), primary_key=True),
        sa.Column("subject", sa.String(500), nullable=False, server_default=""),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("claims_used", sa.JSON, nullable=False),
        sa.Column("disqualify", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("disqualify_reason", sa.String(500), nullable=True),
        sa.Column("needs_human_review", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("status", EMAIL_DRAFT_STATUS, nullable=False, server_default="DRAFTED"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("sent_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("email_drafts")

    op.create_table(
        "outreach_drafts",
        sa.Column("prospect_id", sa.String(64), sa.ForeignKey("prospects.prospect_id"), primary_key=True),
        sa.Column("connection_note", sa.String(280), nullable=False, server_default=""),
        sa.Column("email_sequence", sa.JSON, nullable=False),
        sa.Column("claims_used", sa.JSON, nullable=False),
        sa.Column("disqualify", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("disqualify_reason", sa.String(500), nullable=True),
        sa.Column("needs_human_review", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "review_actions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("prospect_id", sa.String(64), sa.ForeignKey("prospects.prospect_id"), nullable=False),
        sa.Column("action", sa.Enum("APPROVE", "EDIT", "REJECT", name="review_action_type", native_enum=False), nullable=False),
        sa.Column(
            "reject_reason",
            sa.Enum("BAD_FIT", "WEAK_HOOK", "WRONG_FACTS", "TONE", "ALREADY_KNOWN", name="reject_reason", native_enum=False),
            nullable=True,
        ),
        sa.Column("edited_connection_note", sa.String(280), nullable=True),
        sa.Column("edited_email_sequence", sa.JSON, nullable=True),
        sa.Column("edit_distance", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_review_actions_prospect_id", "review_actions", ["prospect_id"])

    op.drop_column("prospects", "last_error_at")
    op.drop_column("prospects", "last_error")
    op.drop_column("prospects", "qualified_at")
    op.drop_column("prospects", "qualification_reason")
    op.alter_column("prospects", "status", type_=sa.String(12), existing_type=PROSPECT_STATUS)
    op.add_column("prospects", sa.Column("pdf_generated_at", sa.DateTime, nullable=True))
    op.add_column("prospects", sa.Column("pdf_path", sa.String(1024), nullable=True))
