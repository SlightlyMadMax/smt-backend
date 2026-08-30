"""add cancelled position status

Revision ID: 6078a1d15d9e
Revises: 61a318f1b0f7
Create Date: 2026-08-30 13:03:57.312394

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6078a1d15d9e'
down_revision: Union[str, None] = '61a318f1b0f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
            ALTER TYPE position_status
            ADD VALUE IF NOT EXISTS 'CANCELLED';
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Downgrade of enum 'CANCELLED' not supported")
