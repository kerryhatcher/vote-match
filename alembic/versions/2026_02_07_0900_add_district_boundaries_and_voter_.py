"""Add district_boundaries and voter_district_assignments tables

Revision ID: a1b2c3d4e5f6
Revises: 2bfc8bbdadbb
Create Date: 2026-02-07 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import geoalchemy2
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "2bfc8bbdadbb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create district_boundaries and voter_district_assignments tables."""
    # Create district_boundaries table
    op.create_table(
        "district_boundaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("district_type", sa.String(length=50), nullable=False),
        sa.Column("district_id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("rep_name", sa.String(length=200), nullable=True),
        sa.Column("party", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("website_url", sa.String(length=500), nullable=True),
        sa.Column("photo_url", sa.String(length=500), nullable=True),
        sa.Column("extra_properties", sa.JSON(), nullable=True),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="GEOMETRY",
                srid=4326,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("district_type", "district_id", name="uq_district_type_id"),
    )
    op.create_index(
        "idx_district_boundary_type", "district_boundaries", ["district_type"], unique=False
    )
    op.create_index(
        "idx_district_boundary_geom",
        "district_boundaries",
        ["geom"],
        unique=False,
        postgresql_using="gist",
    )

    # Create voter_district_assignments table
    op.create_table(
        "voter_district_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("voter_id", sa.String(), nullable=False),
        sa.Column("district_type", sa.String(length=50), nullable=False),
        sa.Column("registered_value", sa.String(length=100), nullable=True),
        sa.Column("spatial_district_id", sa.String(length=50), nullable=True),
        sa.Column("spatial_district_name", sa.String(length=200), nullable=True),
        sa.Column("is_mismatch", sa.Boolean(), nullable=True),
        sa.Column("compared_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["voter_id"], ["voters.voter_registration_number"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voter_id", "district_type", name="uq_voter_district_type"),
    )
    op.create_index("idx_vda_voter", "voter_district_assignments", ["voter_id"], unique=False)
    op.create_index("idx_vda_type", "voter_district_assignments", ["district_type"], unique=False)
    op.create_index("idx_vda_mismatch", "voter_district_assignments", ["is_mismatch"], unique=False)


def downgrade() -> None:
    """Drop district_boundaries and voter_district_assignments tables."""
    op.drop_index("idx_vda_mismatch", table_name="voter_district_assignments")
    op.drop_index("idx_vda_type", table_name="voter_district_assignments")
    op.drop_index("idx_vda_voter", table_name="voter_district_assignments")
    op.drop_table("voter_district_assignments")

    op.drop_index("idx_district_boundary_geom", table_name="district_boundaries")
    op.drop_index("idx_district_boundary_type", table_name="district_boundaries")
    op.drop_table("district_boundaries")
