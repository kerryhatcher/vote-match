"""fix: remove redundant index on district_type

Revision ID: 7ad77dfbda26
Revises: a1b2c3d4e5f6
Create Date: 2026-02-10 10:34:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7ad77dfbda26"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove redundant auto-generated index on district_type if it exists.

    The district_boundaries table should have only one index on district_type:
    - idx_district_boundary_type (explicitly defined in __table_args__)

    This migration removes the redundant auto-generated index if present:
    - ix_district_boundaries_district_type (from Column(index=True))
    """
    # Drop the auto-generated index if it exists
    # SQLAlchemy auto-names these as: ix_<tablename>_<columnname>
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX IF EXISTS ix_district_boundaries_district_type")


def downgrade() -> None:
    """Restore the redundant index (for rollback purposes only)."""
    # Recreate the redundant index if we're rolling back
    op.create_index(
        "ix_district_boundaries_district_type",
        "district_boundaries",
        ["district_type"],
        unique=False,
    )
