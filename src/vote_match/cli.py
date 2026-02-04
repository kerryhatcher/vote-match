"""Command-line interface for Vote Match using Typer."""

import typer
from loguru import logger

from vote_match.config import get_settings
from vote_match.database import init_database
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
def init_db(
    drop: bool = typer.Option(
        False,
        "--drop",
        help="Drop existing tables before creating new ones",
    ),
) -> None:
    """Initialize the PostGIS database schema."""
    logger.info("init-db command called with drop={}", drop)

    settings = get_settings()

    try:
        if drop:
            typer.secho(
                "WARNING: This will drop all existing tables!",
                fg=typer.colors.RED,
                bold=True,
            )
            confirm = typer.confirm("Are you sure you want to continue?")
            if not confirm:
                typer.secho("Operation cancelled", fg=typer.colors.YELLOW)
                raise typer.Abort()

        init_database(drop_tables=drop, settings=settings)

        typer.secho(
            "✓ Database initialized successfully",
            fg=typer.colors.GREEN,
            bold=True,
        )

        if drop:
            typer.secho(
                "  All tables were dropped and recreated",
                fg=typer.colors.YELLOW,
            )
        else:
            typer.secho(
                "  PostGIS extension and tables created",
                fg=typer.colors.GREEN,
            )

    except Exception as e:
        logger.error("Failed to initialize database: {}", str(e))
        typer.secho(
            f"✗ Database initialization failed: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


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
