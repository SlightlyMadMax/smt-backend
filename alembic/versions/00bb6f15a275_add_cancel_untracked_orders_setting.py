"""add cancel_untracked_orders setting

Revision ID: 00bb6f15a275
Revises: e9f88288c1ab
Create Date: 2026-08-30 15:15:42.054275

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00bb6f15a275'
down_revision: Union[str, None] = 'e9f88288c1ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "trading_settings",
        sa.Column("cancel_untracked_orders", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("trading_settings", "cancel_untracked_orders")
