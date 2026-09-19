"""record how the asking price was chosen

Revision ID: dfad880fb114
Revises: 34d4e1b32f1b
Create Date: 2026-09-19 09:50:24.364076

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dfad880fb114'
down_revision: Union[str, None] = '34d4e1b32f1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("pool_items", sa.Column("feasible_round_trips", sa.Integer(), nullable=True))
    op.add_column("pool_items", sa.Column("sell_percentile_used", sa.Integer(), nullable=True))
    op.add_column("pool_items", sa.Column("queue_ahead", sa.Integer(), nullable=True))
    op.add_column("pool_items", sa.Column("days_to_clear", sa.Numeric(10, 1), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("pool_items", "days_to_clear")
    op.drop_column("pool_items", "queue_ahead")
    op.drop_column("pool_items", "sell_percentile_used")
    op.drop_column("pool_items", "feasible_round_trips")
