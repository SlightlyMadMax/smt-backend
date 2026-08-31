"""add action log

Revision ID: f3bb8b24c956
Revises: 00c16754884c
Create Date: 2026-08-31 12:57:31.176259

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3bb8b24c956'
down_revision: Union[str, None] = '00c16754884c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "action_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("market_hash_name", sa.String(length=255), nullable=True),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.String(length=512), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_log_occurred_at", "action_log", ["occurred_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_action_log_occurred_at", table_name="action_log")
    op.drop_table("action_log")
