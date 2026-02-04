"""Add geocode_results table for multi-service geocoding support

Revision ID: 0b5f9c2d8e41
Revises: 6a966ece3941
Create Date: 2026-02-04 13:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0b5f9c2d8e41"
down_revision = "6a966ece3941"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add geocode_results table for storing results from multiple geocoding services."""
    # Create geocode_results table
    op.create_table(
        "geocode_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("voter_id", sa.String(), nullable=False),
        sa.Column("service_name", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("matched_address", sa.Text(), nullable=True),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("raw_response", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("geocoded_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["voter_id"],
            ["voters.voter_registration_number"],
            name="fk_geocode_results_voter_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_geocode_results"),
    )

    # Create indexes
    op.create_index(
        "idx_geocode_results_voter_id",
        "geocode_results",
        ["voter_id"],
        unique=False,
    )
    op.create_index(
        "idx_geocode_results_service_name",
        "geocode_results",
        ["service_name"],
        unique=False,
    )
    op.create_index(
        "idx_geocode_results_status",
        "geocode_results",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_geocode_results_voter_service",
        "geocode_results",
        ["voter_id", "service_name"],
        unique=False,
    )


def downgrade() -> None:
    """Remove geocode_results table."""
    op.drop_index("idx_geocode_results_voter_service", table_name="geocode_results")
    op.drop_index("idx_geocode_results_status", table_name="geocode_results")
    op.drop_index("idx_geocode_results_service_name", table_name="geocode_results")
    op.drop_index("idx_geocode_results_voter_id", table_name="geocode_results")
    op.drop_table("geocode_results")
