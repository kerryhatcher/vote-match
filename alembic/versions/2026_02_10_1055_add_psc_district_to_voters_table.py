"""Add psc_district to voters table

Revision ID: 8e9f0a1b2c3d
Revises: 7ad77dfbda26
Create Date: 2026-02-10 10:55:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8e9f0a1b2c3d"
down_revision: Union[str, Sequence[str], None] = "7ad77dfbda26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add psc_district column to voters table."""
    op.add_column("voters", sa.Column("psc_district", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove psc_district column from voters table."""
    op.drop_column("voters", "psc_district")
