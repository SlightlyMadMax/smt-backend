"""add first_seen_at to items

Revision ID: 61a318f1b0f7
Revises: e2c89fee3d57
Create Date: 2026-08-30 13:01:40.850214

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '61a318f1b0f7'
down_revision: Union[str, None] = 'e2c89fee3d57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "items",
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("items", "first_seen_at")
