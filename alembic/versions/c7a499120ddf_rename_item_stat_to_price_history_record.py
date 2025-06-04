"""Rename item_stat to price_history_record

Revision ID: c7a499120ddf
Revises: be504f24c012
Create Date: 2025-06-04 08:04:13.303303

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7a499120ddf"
down_revision: Union[str, None] = "be504f24c012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.rename_table("item_stats", "price_history_record")


def downgrade():
    op.rename_table("price_history_record", "item_stats")
