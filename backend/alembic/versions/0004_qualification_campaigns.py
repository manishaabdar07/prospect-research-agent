"""qualification campaigns: multiple named, saved criteria sets

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-30

Evolves the single global qualification_criteria table (added in 0003) into
several named QualificationCampaigns, each with its own criteria and decision
rule (min_optional_matches), so different qualification runs can use
completely different configured criteria without touching code. Also adds
per-criterion `mandatory` (replacing the old global qualification_rule_settings
ALL/MIN_MATCH singleton, which is dropped) and stamps each prospect with which
campaign evaluated it, frozen at evaluation time.

Seeds one "Default" campaign, marks it active, and reattaches the 4 existing
criteria to it with mandatory=True -- byte-identical behavior to before this
migration runs.

Hand-written, mirroring app/models.py exactly (see 0001_initial.py for why:
no live Postgres to autogenerate against in this environment).
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qualification_campaigns",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("min_optional_matches", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    now = datetime.utcnow()
    bind = op.get_bind()
    campaigns_table = sa.table(
        "qualification_campaigns",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("min_optional_matches", sa.Integer),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    bind.execute(
        campaigns_table.insert().values(
            name="Default", description="", is_active=True, min_optional_matches=None,
            created_at=now, updated_at=now,
        )
    )
    default_campaign_id = bind.execute(
        sa.select(campaigns_table.c.id).where(campaigns_table.c.name == "Default")
    ).scalar_one()

    op.add_column("qualification_criteria", sa.Column("campaign_id", sa.Integer, nullable=True))
    op.add_column(
        "qualification_criteria",
        sa.Column("mandatory", sa.Boolean, nullable=False, server_default=sa.true()),
    )

    criteria_table = sa.table("qualification_criteria", sa.column("campaign_id", sa.Integer))
    bind.execute(criteria_table.update().values(campaign_id=default_campaign_id))

    op.alter_column("qualification_criteria", "campaign_id", nullable=False)
    op.create_foreign_key(
        "fk_qualification_criteria_campaign_id", "qualification_criteria",
        "qualification_campaigns", ["campaign_id"], ["id"],
    )

    op.add_column("prospects", sa.Column("qualification_campaign_id", sa.Integer, nullable=True))
    op.add_column("prospects", sa.Column("qualification_campaign_name", sa.String(255), nullable=True))
    op.create_foreign_key(
        "fk_prospects_qualification_campaign_id", "prospects",
        "qualification_campaigns", ["qualification_campaign_id"], ["id"],
        ondelete="SET NULL",
    )

    op.drop_table("qualification_rule_settings")


def downgrade() -> None:
    RULE_MODE = sa.Enum("ALL", "MIN_MATCH", name="rule_mode", native_enum=False)
    op.create_table(
        "qualification_rule_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mode", RULE_MODE, nullable=False, server_default="ALL"),
        sa.Column("min_matches", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    now = datetime.utcnow()
    op.execute(
        sa.table(
            "qualification_rule_settings",
            sa.column("id", sa.Integer), sa.column("mode", RULE_MODE),
            sa.column("min_matches", sa.Integer), sa.column("updated_at", sa.DateTime),
        ).insert().values(id=1, mode="ALL", min_matches=None, updated_at=now)
    )

    op.drop_constraint("fk_prospects_qualification_campaign_id", "prospects", type_="foreignkey")
    op.drop_column("prospects", "qualification_campaign_name")
    op.drop_column("prospects", "qualification_campaign_id")

    op.drop_constraint("fk_qualification_criteria_campaign_id", "qualification_criteria", type_="foreignkey")
    op.drop_column("qualification_criteria", "mandatory")
    op.drop_column("qualification_criteria", "campaign_id")

    op.drop_table("qualification_campaigns")
