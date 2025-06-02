"""create pool items table

Revision ID: ebb79532a6ee
Revises: 0cbe7bbe9ce2
Create Date: 2025-06-02 21:29:26.661507

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ebb79532a6ee"
down_revision: Union[str, None] = "0cbe7bbe9ce2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
