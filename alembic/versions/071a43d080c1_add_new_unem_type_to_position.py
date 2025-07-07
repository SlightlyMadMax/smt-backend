"""add new unem type to position

Revision ID: 071a43d080c1
Revises: a2e48825e292
Create Date: 2025-07-07 14:04:50.217134

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "071a43d080c1"
down_revision: Union[str, None] = "a2e48825e292"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
            ALTER TYPE position_status 
            ADD VALUE IF NOT EXISTS 'BOUGHT';
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Downgrade of enum 'BOUGHT' not supported")
