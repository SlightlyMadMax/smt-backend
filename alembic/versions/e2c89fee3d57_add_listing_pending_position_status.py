"""add listing_pending position status

Revision ID: e2c89fee3d57
Revises: f18a1e46ec57
Create Date: 2026-08-30 12:52:44.710689

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2c89fee3d57'
down_revision: Union[str, None] = 'f18a1e46ec57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
            ALTER TYPE position_status
            ADD VALUE IF NOT EXISTS 'LISTING_PENDING';
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Downgrade of enum 'LISTING_PENDING' not supported")
