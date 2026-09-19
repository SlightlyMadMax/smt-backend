"""drop settings the other checks already cover

Revision ID: f790ccbfd0f5
Revises: dfad880fb114
Create Date: 2026-09-19 18:54:38.974399

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f790ccbfd0f5'
down_revision: Union[str, None] = 'dfad880fb114'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("trading_settings", "min_profit_percentage")
    op.drop_column("trading_settings", "min_volatility_threshold")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "trading_settings",
        sa.Column("min_volatility_threshold", sa.Numeric(10, 3), nullable=True, server_default="0.010"),
    )
    op.add_column(
        "trading_settings",
        sa.Column("min_profit_percentage", sa.Numeric(5, 2), nullable=True, server_default="5.00"),
    )
