"""add weekly volume to pool items

Revision ID: 00c16754884c
Revises: e1595ea6b130
Create Date: 2026-08-30 18:51:36.484607

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00c16754884c'
down_revision: Union[str, None] = 'e1595ea6b130'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("pool_items", sa.Column("current_volume7d", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("pool_items", "current_volume7d")
