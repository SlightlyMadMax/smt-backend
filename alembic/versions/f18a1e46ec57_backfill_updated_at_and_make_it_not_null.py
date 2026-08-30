"""backfill updated_at and make it not null

Revision ID: f18a1e46ec57
Revises: 6ffd2e64a5a7
Create Date: 2026-08-30 12:50:15.505898

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f18a1e46ec57'
down_revision: Union[str, None] = '6ffd2e64a5a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = ("pool_items", "trading_settings", "positions")


def upgrade() -> None:
    """Upgrade schema."""
    for table in TABLES:
        op.execute(f"UPDATE {table} SET updated_at = created_at WHERE updated_at IS NULL")
        op.alter_column(
            table,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in TABLES:
        op.alter_column(
            table,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=None,
            nullable=True,
        )
