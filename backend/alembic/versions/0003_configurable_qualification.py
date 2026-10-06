"""configurable qualification criteria

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30

Adds the qualification_criteria / qualification_rule_settings tables and
Prospect.qualification_details, then seeds rows that reproduce today's
hardcoded Stage 2 behavior exactly (Headcount Band 10-200, the 14-city
Pune-metro allowlist, Exclusion List, Duplicate Check, decision mode=ALL) --
purely additive, no existing data is touched.

Hand-written, mirroring app/models.py exactly (see 0001_initial.py for why:
no live Postgres to autogenerate against in this environment).
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CRITERION_TYPE = sa.Enum(
    "RANGE", "LIST", "EXACT_MATCH", "CONTAINS", "BOOLEAN", "EXCLUSION_LIST", "DUPLICATE_CHECK",
    name="criterion_type", native_enum=False,
)
RULE_MODE = sa.Enum("ALL", "MIN_MATCH", name="rule_mode", native_enum=False)

PUNE_METRO_ALLOWLIST = [
    "pune", "pimpri-chinchwad", "chakan", "hinjewadi", "talegaon", "ranjangaon",
    "chikhali", "wagholi", "hadapsar", "baner", "kharadi", "bhosari", "manjari", "shirwal",
]

qualification_criteria = sa.table(
    "qualification_criteria",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("criterion_type", CRITERION_TYPE),
    sa.column("field", sa.String),
    sa.column("configuration", sa.JSON),
    sa.column("enabled", sa.Boolean),
    sa.column("priority", sa.Integer),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)

qualification_rule_settings = sa.table(
    "qualification_rule_settings",
    sa.column("id", sa.Integer),
    sa.column("mode", RULE_MODE),
    sa.column("min_matches", sa.Integer),
    sa.column("updated_at", sa.DateTime),
)


def upgrade() -> None:
    op.add_column("prospects", sa.Column("qualification_details", sa.JSON, nullable=True))

    op.create_table(
        "qualification_criteria",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("criterion_type", CRITERION_TYPE, nullable=False),
        sa.Column("field", sa.String(128), nullable=True),
        sa.Column("configuration", sa.JSON, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "qualification_rule_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mode", RULE_MODE, nullable=False, server_default="ALL"),
        sa.Column("min_matches", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    now = datetime.utcnow()
    op.bulk_insert(
        qualification_criteria,
        [
            {
                "name": "Headcount Band",
                "criterion_type": "RANGE",
                "field": "company.headcount",
                "configuration": {"min": 10, "max": 200},
                "enabled": True,
                "priority": 10,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "City Allowlist",
                "criterion_type": "LIST",
                "field": "company.city",
                "configuration": {"allowed_values": PUNE_METRO_ALLOWLIST},
                "enabled": True,
                "priority": 20,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "Exclusion List",
                "criterion_type": "EXCLUSION_LIST",
                "field": None,
                "configuration": {},
                "enabled": True,
                "priority": 30,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "Duplicate Check",
                "criterion_type": "DUPLICATE_CHECK",
                "field": None,
                "configuration": {},
                "enabled": True,
                "priority": 40,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )
    op.bulk_insert(
        qualification_rule_settings,
        [{"id": 1, "mode": "ALL", "min_matches": None, "updated_at": now}],
    )


def downgrade() -> None:
    op.drop_table("qualification_rule_settings")
    op.drop_table("qualification_criteria")
    op.drop_column("prospects", "qualification_details")
