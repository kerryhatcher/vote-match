"""Database migration utilities using Alembic."""

from pathlib import Path
from typing import Optional

from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from loguru import logger
from sqlalchemy import create_engine, text

from vote_match.config import get_settings


def get_alembic_config() -> Config:
    """
    Get Alembic configuration object.

    Returns:
        Configured Alembic Config object

    Raises:
        FileNotFoundError: If alembic.ini is not found
    """
    # Find alembic.ini in project root (3 levels up from this file)
    project_root = Path(__file__).parent.parent.parent
    alembic_ini = project_root / "alembic.ini"

    if not alembic_ini.exists():
        raise FileNotFoundError(f"Alembic config not found: {alembic_ini}")

    logger.debug("Loading Alembic config from: {}", alembic_ini)
    config = Config(str(alembic_ini))

    # Set alembic directory location
    alembic_dir = project_root / "alembic"
    config.set_main_option("script_location", str(alembic_dir))

    logger.debug("Alembic script location: {}", alembic_dir)
    return config


def create_migration(message: str, autogenerate: bool = True) -> None:
    """
    Create a new migration file.

    Args:
        message: Migration description message
        autogenerate: If True, auto-detect model changes (default: True)

    Raises:
        Exception: If migration creation fails
    """
    logger.info("Creating migration: {}", message)
    config = get_alembic_config()

    try:
        alembic_command.revision(
            config,
            message=message,
            autogenerate=autogenerate,
        )
        logger.info("Migration created successfully")
    except Exception as e:
        logger.error("Failed to create migration: {}", str(e))
        raise


def upgrade_database(revision: str = "head") -> None:
    """
    Upgrade database to a specific revision.

    Args:
        revision: Target revision (default: "head" for latest)

    Raises:
        Exception: If upgrade fails
    """
    logger.info("Upgrading database to revision: {}", revision)
    config = get_alembic_config()

    try:
        alembic_command.upgrade(config, revision)
        logger.info("Database upgraded successfully to: {}", revision)
    except Exception as e:
        logger.error("Failed to upgrade database: {}", str(e))
        raise


def downgrade_database(revision: str) -> None:
    """
    Downgrade database to a specific revision.

    Args:
        revision: Target revision to downgrade to

    Raises:
        Exception: If downgrade fails
    """
    logger.info("Downgrading database to revision: {}", revision)
    config = get_alembic_config()

    try:
        alembic_command.downgrade(config, revision)
        logger.info("Database downgraded successfully to: {}", revision)
    except Exception as e:
        logger.error("Failed to downgrade database: {}", str(e))
        raise


def show_current_revision() -> Optional[str]:
    """
    Get the current database migration revision.

    Returns:
        Current revision string or None if no migrations applied
    """
    logger.debug("Checking current database revision")
    settings = get_settings()
    engine = create_engine(settings.database_url, echo=False)

    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current_rev = context.get_current_revision()
            logger.debug("Current revision: {}", current_rev)
            return current_rev
    except Exception as e:
        logger.error("Failed to get current revision: {}", str(e))
        raise
    finally:
        engine.dispose()


def show_history() -> list[tuple[str, str]]:
    """
    Get list of all migrations with their descriptions.

    Returns:
        List of (revision, description) tuples
    """
    logger.debug("Retrieving migration history")
    config = get_alembic_config()

    try:
        script = ScriptDirectory.from_config(config)
        revisions = []

        for revision in script.walk_revisions():
            revisions.append((revision.revision, revision.doc or "(no description)"))

        logger.debug("Found {} migrations", len(revisions))
        return revisions
    except Exception as e:
        logger.error("Failed to get migration history: {}", str(e))
        raise
