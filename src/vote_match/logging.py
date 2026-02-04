"""Logging configuration for Vote Match using loguru."""

import sys
from pathlib import Path

from loguru import logger

from vote_match.config import Settings


def setup_logging(settings: Settings) -> None:
    """
    Configure loguru logging based on settings.

    Args:
        settings: Application settings containing log level and file path.
    """
    # Remove default handler
    logger.remove()

    # Add console handler with configured level
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # Ensure log directory exists
    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Add file handler with rotation
    logger.add(
        settings.log_file,
        level=settings.log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
    )

    logger.info("Logging configured: level={}, file={}", settings.log_level, settings.log_file)
