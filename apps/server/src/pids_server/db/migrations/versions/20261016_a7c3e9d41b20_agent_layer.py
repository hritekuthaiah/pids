"""agent layer: procedure index (pgvector + full text) and agent reports

Revision ID: a7c3e9d41b20
Revises: fcdb01fb2145
Create Date: 2026-10-16 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "a7c3e9d41b20"
down_revision: str | None = "fcdb01fb2145"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "procedure_chunks",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("doc", sa.String(120), nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("heading", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', heading || ' ' || body)", persisted=True),
        ),
    )
    op.create_index("ix_procedure_chunks_tsv", "procedure_chunks", ["tsv"], postgresql_using="gin")
    op.create_table(
        "agent_reports",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "alert_id",
            sa.String(200),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "site_id", sa.String(64), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("requested_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("decisions", postgresql.JSONB(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_reports")
    op.drop_index("ix_procedure_chunks_tsv", table_name="procedure_chunks")
    op.drop_table("procedure_chunks")
