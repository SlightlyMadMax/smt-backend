"""record realized profit on positions

Revision ID: 1c618d0f9502
Revises: 00bb6f15a275
Create Date: 2026-08-30 17:05:40.446663

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c618d0f9502'
down_revision: Union[str, None] = '00bb6f15a275'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("positions", sa.Column("net_proceeds", sa.Numeric(10, 2), nullable=True))
    op.add_column("positions", sa.Column("realized_profit", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("positions", "realized_profit")
    op.drop_column("positions", "net_proceeds")
