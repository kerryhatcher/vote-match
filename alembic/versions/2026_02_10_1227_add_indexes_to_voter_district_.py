"""add indexes to voter_district_assignments for performance

Revision ID: b53ae1b6eba4
Revises: cc180756961f
Create Date: 2026-02-10 12:27:19.945570

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b53ae1b6eba4'
down_revision: Union[str, Sequence[str], None] = 'cc180756961f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add composite indexes for faster filtering by district type and mismatch status
    op.create_index('idx_vda_type_mismatch', 'voter_district_assignments', ['district_type', 'is_mismatch'], unique=False)
    op.create_index('idx_vda_voter_mismatch', 'voter_district_assignments', ['voter_id', 'is_mismatch'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove composite indexes
    op.drop_index('idx_vda_voter_mismatch', table_name='voter_district_assignments')
    op.drop_index('idx_vda_type_mismatch', table_name='voter_district_assignments')
