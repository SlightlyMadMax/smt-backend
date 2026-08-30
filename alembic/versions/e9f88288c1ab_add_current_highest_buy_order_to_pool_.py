"""add current_highest_buy_order to pool items

Revision ID: e9f88288c1ab
Revises: 6078a1d15d9e
Create Date: 2026-08-30 14:23:23.048960

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f88288c1ab'
down_revision: Union[str, None] = '6078a1d15d9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("pool_items", sa.Column("current_highest_buy_order", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("pool_items", "current_highest_buy_order")
