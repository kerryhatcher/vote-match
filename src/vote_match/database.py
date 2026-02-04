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


def init_database(drop_tables: bool, settings: Settings) -> None:
    """
    Initialize PostGIS database schema.

    Creates the PostGIS extension if it doesn't exist, then creates all tables.
    Optionally drops existing tables first.

    Args:
        drop_tables: If True, drop all existing tables before creating new ones
        settings: Application settings containing database URL

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
            logger.warning("Dropping all existing tables")
            Base.metadata.drop_all(engine)
            logger.info("All tables dropped")

        # Create tables
        logger.debug("Creating database tables")
        Base.metadata.create_all(engine)
        logger.info("Database tables created successfully")

    except Exception as e:
        logger.error("Failed to initialize database: {}", str(e))
        raise
    finally:
        engine.dispose()
