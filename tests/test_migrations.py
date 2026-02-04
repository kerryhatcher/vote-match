"""Tests for database migration functionality."""

from sqlalchemy import create_engine, inspect, text

from vote_match.config import Settings
from vote_match.database import init_database
from vote_match.migrations import (
    upgrade_database,
    downgrade_database,
    show_current_revision,
)


class TestInitDbWithMigrations:
    """Tests for initializing database with migrations."""

    def test_init_db_with_migrations(self, test_settings: Settings):
        """Test that init_database creates alembic_version table and sets current revision."""
        # Initialize database with migrations
        init_database(drop_tables=True, settings=test_settings, run_migrations=True)

        # Create engine and inspector
        engine = create_engine(test_settings.database_url)
        inspector = inspect(engine)

        try:
            # Verify alembic_version table exists
            tables = inspector.get_table_names()
            assert "alembic_version" in tables, "alembic_version table should be created"

            # Verify current revision is set
            current_revision = show_current_revision()
            assert current_revision is not None, "Current revision should be set after init"
            assert len(current_revision) > 0, "Current revision should not be empty"

            # Verify voters table was created
            assert "voters" in tables, "voters table should be created"

        finally:
            engine.dispose()

    def test_init_db_without_migrations(self, test_settings: Settings):
        """Test that init_database with run_migrations=False skips migration setup."""
        # Initialize database without migrations
        init_database(drop_tables=True, settings=test_settings, run_migrations=False)

        # Create engine and inspector
        engine = create_engine(test_settings.database_url)
        inspector = inspect(engine)

        try:
            # Verify alembic_version table does NOT exist
            tables = inspector.get_table_names()
            assert "alembic_version" not in tables, "alembic_version should not exist when migrations skipped"

            # Verify voters table was still created
            assert "voters" in tables, "voters table should be created even without migrations"

        finally:
            engine.dispose()


class TestMigrationUpgradeDowngrade:
    """Tests for migration upgrade and downgrade operations."""

    def test_migration_upgrade_downgrade(self, test_settings: Settings):
        """Test full migration cycle: upgrade to head, then downgrade."""
        # Initialize database with migrations
        init_database(drop_tables=True, settings=test_settings, run_migrations=True)

        # Create engine and inspector
        engine = create_engine(test_settings.database_url)
        inspector = inspect(engine)

        try:
            # Verify alembic_version table exists
            tables = inspector.get_table_names()
            assert "alembic_version" in tables, "alembic_version table should exist"

            # Get current revision (should be at head after init)
            current_rev = show_current_revision()
            assert current_rev is not None, "Should have a current revision"

            # Verify we can check the revision in alembic_version table
            with engine.connect() as conn:
                result = conn.execute(text("SELECT version_num FROM alembic_version;"))
                version = result.scalar()
                assert version == current_rev, "Revision in table should match current revision"
                conn.commit()

            # Test downgrade to base
            downgrade_database("base")

            # Verify revision is cleared
            current_rev_after_downgrade = show_current_revision()
            assert current_rev_after_downgrade is None, "Revision should be None after downgrading to base"

            # Verify voters table was dropped by downgrade
            inspector = inspect(engine)
            tables_after_downgrade = inspector.get_table_names()
            assert "voters" not in tables_after_downgrade, "voters table should be removed after downgrade"

            # Test upgrade back to head
            upgrade_database("head")

            # Verify revision is set again
            current_rev_after_upgrade = show_current_revision()
            assert current_rev_after_upgrade is not None, "Revision should be set after upgrade"
            assert current_rev_after_upgrade == current_rev, "Should be back at original revision"

            # Verify voters table was recreated
            inspector = inspect(engine)
            tables_after_upgrade = inspector.get_table_names()
            assert "voters" in tables_after_upgrade, "voters table should be recreated after upgrade"

        finally:
            engine.dispose()


class TestDbStampExistingDatabase:
    """Tests for stamping an existing database."""

    def test_db_stamp_existing_database(self, test_settings: Settings):
        """Test stamping an existing database without running migrations."""
        from alembic import command as alembic_command
        from vote_match.migrations import get_alembic_config

        # Initialize database WITHOUT migrations (simulates existing database)
        init_database(drop_tables=True, settings=test_settings, run_migrations=False)

        # Create engine and inspector
        engine = create_engine(test_settings.database_url)
        inspector = inspect(engine)

        try:
            # Verify alembic_version table does NOT exist yet
            tables = inspector.get_table_names()
            assert "alembic_version" not in tables, "alembic_version should not exist before stamping"

            # Verify voters table exists (from init_database)
            assert "voters" in tables, "voters table should exist from init"

            # Stamp the database at head revision
            config = get_alembic_config()
            alembic_command.stamp(config, "head")

            # Verify alembic_version table now exists
            inspector = inspect(engine)
            tables_after_stamp = inspector.get_table_names()
            assert "alembic_version" in tables_after_stamp, "alembic_version should exist after stamping"

            # Verify current revision is set
            current_rev = show_current_revision()
            assert current_rev is not None, "Current revision should be set after stamping"

            # Verify voters table still exists (stamping doesn't modify schema)
            assert "voters" in tables_after_stamp, "voters table should still exist after stamping"

            # Verify we can check the revision
            with engine.connect() as conn:
                result = conn.execute(text("SELECT version_num FROM alembic_version;"))
                version = result.scalar()
                assert version == current_rev, "Stamped revision should match current revision"
                conn.commit()

        finally:
            engine.dispose()
