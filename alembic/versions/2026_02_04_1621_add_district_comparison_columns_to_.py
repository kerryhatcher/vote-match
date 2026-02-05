"""Add district comparison columns to voters table

Revision ID: 2bfc8bbdadbb
Revises: 5c6d93e0e85d
Create Date: 2026-02-04 16:21:17.841434

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "2bfc8bbdadbb"
down_revision: Union[str, Sequence[str], None] = "5c6d93e0e85d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add district comparison columns to voters table
    op.add_column("voters", sa.Column("spatial_district_id", sa.String(length=10), nullable=True))
    op.add_column(
        "voters", sa.Column("spatial_district_name", sa.String(length=100), nullable=True)
    )
    op.add_column("voters", sa.Column("district_mismatch", sa.Boolean(), nullable=True))
    op.add_column("voters", sa.Column("district_compared_at", sa.DateTime(), nullable=True))
    op.create_index(
        op.f("ix_voters_district_mismatch"), "voters", ["district_mismatch"], unique=False
    )
    op.create_index(
        op.f("ix_voters_spatial_district_id"), "voters", ["spatial_district_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove district comparison columns from voters table
    op.drop_index(op.f("ix_voters_spatial_district_id"), table_name="voters")
    op.drop_index(op.f("ix_voters_district_mismatch"), table_name="voters")
    op.drop_column("voters", "district_compared_at")
    op.drop_column("voters", "district_mismatch")
    op.drop_column("voters", "spatial_district_name")
    op.drop_column("voters", "spatial_district_id")
