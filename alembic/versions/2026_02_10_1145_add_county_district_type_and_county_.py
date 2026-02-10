"""Add county district type and county_name column to district_boundaries

Revision ID: cc180756961f
Revises: 8e9f0a1b2c3d
Create Date: 2026-02-10 11:45:22.178215

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "cc180756961f"
down_revision: Union[str, Sequence[str], None] = "8e9f0a1b2c3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add county_name column to district_boundaries table for filtering."""
    # Add county_name column to district_boundaries
    op.add_column(
        "district_boundaries", sa.Column("county_name", sa.String(length=100), nullable=True)
    )

    # Add index on county_name for efficient filtering
    op.create_index(
        "idx_district_boundary_county", "district_boundaries", ["county_name"], unique=False
    )


def downgrade() -> None:
    """Remove county_name column from district_boundaries table."""
    # Drop the index
    op.drop_index("idx_district_boundary_county", table_name="district_boundaries")

    # Drop the column
    op.drop_column("district_boundaries", "county_name")
