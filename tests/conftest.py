"""Pytest configuration and fixtures for Vote Match tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from vote_match.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    """
    Provide test settings with in-memory database.

    Returns:
        Settings instance configured for testing.
    """
    return Settings(
        database_url="postgresql+psycopg://test:test@localhost:5432/vote_match_test",
        log_level="DEBUG",
        log_file="logs/test.log",
        default_state="GA",
        default_batch_size=100,
        census_timeout=30,
    )


@pytest.fixture
def db_engine(test_settings: Settings):
    """
    Provide a SQLAlchemy engine for testing.

    Args:
        test_settings: Test settings fixture.

    Returns:
        SQLAlchemy engine instance.
    """
    engine = create_engine(test_settings.database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Session:
    """
    Provide a SQLAlchemy session for testing with automatic rollback.

    Args:
        db_engine: Database engine fixture.

    Yields:
        SQLAlchemy session instance.
    """
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
