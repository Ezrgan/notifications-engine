"""create clients and notifications

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-08-14 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("hashed_api_key", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hashed_api_key"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("template", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notifications_client_id"),
        "notifications",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        "uq_notifications_client_idempotency",
        "notifications",
        ["client_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_notifications_client_idempotency",
        table_name="notifications",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index(op.f("ix_notifications_client_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("clients")
