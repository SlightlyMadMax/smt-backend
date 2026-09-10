"""detach positions from the pool

Revision ID: 34d4e1b32f1b
Revises: f3bb8b24c956
Create Date: 2026-09-10 22:39:03.577154

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '34d4e1b32f1b'
down_revision: Union[str, None] = 'f3bb8b24c956'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("positions", sa.Column("app_id", sa.String(length=32), nullable=True))
    op.add_column("positions", sa.Column("context_id", sa.String(length=64), nullable=True))

    op.execute(
        """
        UPDATE positions p
           SET app_id = i.app_id,
               context_id = i.context_id
          FROM pool_items i
         WHERE i.market_hash_name = p.pool_item_hash
        """
    )
    op.execute("UPDATE positions SET app_id = '440' WHERE app_id IS NULL")
    op.execute("UPDATE positions SET context_id = '2' WHERE context_id IS NULL")

    op.alter_column("positions", "app_id", nullable=False)
    op.alter_column("positions", "context_id", nullable=False)

    op.drop_constraint("positions_pool_item_hash_fkey", "positions", type_="foreignkey")
    op.create_index("ix_positions_pool_item_hash", "positions", ["pool_item_hash"])


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        DELETE FROM positions
         WHERE pool_item_hash NOT IN (SELECT market_hash_name FROM pool_items)
        """
    )
    op.drop_index("ix_positions_pool_item_hash", table_name="positions")
    op.create_foreign_key(
        "positions_pool_item_hash_fkey",
        "positions",
        "pool_items",
        ["pool_item_hash"],
        ["market_hash_name"],
        ondelete="CASCADE",
    )
    op.drop_column("positions", "context_id")
    op.drop_column("positions", "app_id")
