"""Command-line interface for Vote Match using Typer."""

import typer
from loguru import logger

from vote_match.config import get_settings
from vote_match.logging import setup_logging

app = typer.Typer(
    name="vote-match",
    help="Vote Match: Process voter registration records for GIS applications",
    add_completion=True,
)

# Global state for verbose flag
_verbose = False


@app.callback()
def main(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging (DEBUG level)",
    ),
) -> None:
    """
    Vote Match CLI - Process voter registration records for GIS applications.
    """
    global _verbose
    _verbose = verbose

    # Load settings and configure logging
    settings = get_settings()
    if verbose:
        settings.log_level = "DEBUG"
    setup_logging(settings)

    logger.debug("Verbose mode enabled")


@app.command()
def init_db() -> None:
    """Initialize the PostGIS database schema."""
    logger.info("init-db command called")
    typer.echo("Not implemented yet")


@app.command()
def load_csv(
    csv_file: str = typer.Argument(..., help="Path to voter registration CSV file"),
) -> None:
    """Load voter registration data from CSV into the database."""
    logger.info("load-csv command called with file: {}", csv_file)
    typer.echo("Not implemented yet")


@app.command()
def geocode(
    batch_size: int = typer.Option(
        None,
        "--batch-size",
        "-b",
        help="Number of records to process per batch",
    ),
) -> None:
    """Geocode voter addresses using Census geocoding service."""
    logger.info("geocode command called with batch_size: {}", batch_size)
    typer.echo("Not implemented yet")


@app.command()
def status() -> None:
    """Display status of voter records (loaded, geocoded, matched)."""
    logger.info("status command called")
    typer.echo("Not implemented yet")


@app.command()
def export(
    output_file: str = typer.Argument(..., help="Path to output file"),
    format: str = typer.Option(
        "geojson",
        "--format",
        "-f",
        help="Output format (geojson, shapefile, csv)",
    ),
) -> None:
    """Export processed voter data to various formats."""
    logger.info("export command called with output_file: {}, format: {}", output_file, format)
    typer.echo("Not implemented yet")


if __name__ == "__main__":
    app()
