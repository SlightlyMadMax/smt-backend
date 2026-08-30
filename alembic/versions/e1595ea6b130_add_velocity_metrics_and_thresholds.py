"""add velocity metrics and thresholds

Revision ID: e1595ea6b130
Revises: 1c618d0f9502
Create Date: 2026-08-30 18:32:58.634288

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1595ea6b130'
down_revision: Union[str, None] = '1c618d0f9502'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("pool_items", sa.Column("round_trips", sa.Integer(), nullable=True))
    op.add_column("pool_items", sa.Column("median_hold_hours", sa.Numeric(10, 1), nullable=True))
    op.add_column("pool_items", sa.Column("return_on_capital_30d", sa.Numeric(10, 1), nullable=True))
    op.add_column(
        "trading_settings",
        sa.Column("max_hold_hours", sa.Integer(), nullable=False, server_default="48"),
    )
    op.add_column(
        "trading_settings",
        sa.Column("min_return_on_capital_30d", sa.Numeric(10, 1), nullable=False, server_default="20.0"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("trading_settings", "min_return_on_capital_30d")
    op.drop_column("trading_settings", "max_hold_hours")
    op.drop_column("pool_items", "return_on_capital_30d")
    op.drop_column("pool_items", "median_hold_hours")
    op.drop_column("pool_items", "round_trips")
