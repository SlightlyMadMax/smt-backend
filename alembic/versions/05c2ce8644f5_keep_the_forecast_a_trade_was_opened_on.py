"""keep the forecast a trade was opened on

Revision ID: 05c2ce8644f5
Revises: f790ccbfd0f5
Create Date: 2026-09-19 20:07:46.915919

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05c2ce8644f5'
down_revision: Union[str, None] = 'f790ccbfd0f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("positions", sa.Column("forecast_profit", sa.Numeric(10, 2), nullable=True))
    op.add_column("positions", sa.Column("forecast_hold_hours", sa.Numeric(10, 1), nullable=True))
    op.add_column("positions", sa.Column("forecast_days_to_clear", sa.Numeric(10, 1), nullable=True))
    op.add_column("positions", sa.Column("forecast_return_30d", sa.Numeric(10, 1), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("positions", "forecast_return_30d")
    op.drop_column("positions", "forecast_days_to_clear")
    op.drop_column("positions", "forecast_hold_hours")
    op.drop_column("positions", "forecast_profit")
