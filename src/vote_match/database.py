"""Database connection and initialization for Vote Match application."""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from loguru import logger

from vote_match.config import Settings
from vote_match.models import Base


def get_engine(settings: Settings) -> Engine:
    """
    Create SQLAlchemy engine from settings.

    Args:
        settings: Application settings containing database URL

    Returns:
        SQLAlchemy Engine instance
    """
    logger.debug("Creating database engine with URL: {}", settings.database_url)
    engine = create_engine(settings.database_url, echo=False)
    return engine


def get_session(engine: Engine) -> Session:
    """
    Create a new database session.

    Args:
        engine: SQLAlchemy Engine instance

    Returns:
        New SQLAlchemy Session instance
    """
    return Session(engine)


def init_database(drop_tables: bool, settings: Settings, run_migrations: bool = True) -> None:
    """
    Initialize PostGIS database schema.

    Creates the PostGIS extension if it doesn't exist, optionally drops tables,
    and runs database migrations if requested.

    Args:
        drop_tables: If True, drop all existing tables and migration history before creating new ones
        settings: Application settings containing database URL
        run_migrations: If True, run database migrations after initialization (default: True)

    Raises:
        Exception: If database initialization fails
    """
    logger.info("Initializing database schema")

    # Get engine
    engine = get_engine(settings)

    try:
        # Create PostGIS extension
        with engine.connect() as conn:
            logger.debug("Creating PostGIS extension")
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            conn.commit()
            logger.info("PostGIS extension created or already exists")

        # Drop tables if requested
        if drop_tables:
            logger.warning("Dropping all existing tables and migration history")
            with engine.connect() as conn:
                # Drop alembic_version table to clear migration history
                conn.execute(text("DROP TABLE IF EXISTS alembic_version;"))
                conn.commit()
                logger.debug("Alembic version table dropped")

            Base.metadata.drop_all(engine)
            logger.info("All tables dropped")

        # Run migrations if requested
        if run_migrations:
            logger.info("Running database migrations")
            from vote_match.migrations import upgrade_database

            upgrade_database("head")
            logger.info("Database migrations completed")
        else:
            logger.info("Skipping database migrations (run_migrations=False)")
            # Create tables directly if not using migrations
            logger.debug("Creating database tables directly")
            Base.metadata.create_all(engine)
            logger.info("Database tables created successfully")

    except Exception as e:
        logger.error("Failed to initialize database: {}", str(e))
        raise
    finally:
        engine.dispose()
