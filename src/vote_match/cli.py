"""Command-line interface for Vote Match using Typer."""

from pathlib import Path

import typer
from loguru import logger
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vote_match.config import get_settings
from vote_match.database import init_database, get_engine, get_session
from vote_match.logging import setup_logging
from vote_match.csv_reader import read_voter_csv, dataframe_to_dicts
from vote_match.models import Voter

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
    csv_file: Path = typer.Argument(..., help="Path to voter registration CSV file"),
    truncate: bool = typer.Option(
        False,
        "--truncate",
        help="Clear all existing voter records before loading",
    ),
) -> None:
    """Load voter registration data from CSV into the database."""
    logger.info("load-csv command called with file: {}", csv_file)

    settings = get_settings()

    try:
        # Read and validate CSV
        typer.echo(f"Reading CSV file: {csv_file}")
        df = read_voter_csv(str(csv_file))
        total_records = len(df)
        logger.info("Loaded {} records from CSV", total_records)

        # Convert to dictionaries
        records = dataframe_to_dicts(df)

        # Get database connection
        engine = get_engine(settings)
        session = get_session(engine)

        try:
            # Truncate table if requested
            if truncate:
                typer.secho(
                    "WARNING: About to delete all existing voter records!",
                    fg=typer.colors.RED,
                    bold=True,
                )
                confirm = typer.confirm("Are you sure you want to continue?")
                if not confirm:
                    typer.secho("Operation cancelled", fg=typer.colors.YELLOW)
                    raise typer.Abort()

                logger.warning("Truncating voters table")
                session.execute(delete(Voter))
                session.commit()
                typer.secho("✓ Existing records deleted", fg=typer.colors.YELLOW)

            # Insert records in batches with progress bar
            batch_size = 1000
            total_batches = (total_records + batch_size - 1) // batch_size

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                transient=False,
            ) as progress:
                task = progress.add_task(
                    "Loading records...",
                    total=total_records,
                )

                for i in range(0, total_records, batch_size):
                    batch = records[i : i + batch_size]
                    batch_num = (i // batch_size) + 1

                    logger.info(
                        "Processing batch {}/{} ({} records)",
                        batch_num,
                        total_batches,
                        len(batch),
                    )

                    # Use PostgreSQL's INSERT ... ON CONFLICT for upsert
                    stmt = pg_insert(Voter).values(batch)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["voter_registration_number"],
                        set_={
                            col: stmt.excluded[col]
                            for col in batch[0].keys()
                            if col != "voter_registration_number"
                        },
                    )

                    session.execute(stmt)
                    session.commit()

                    progress.update(task, advance=len(batch))

            session.close()
            engine.dispose()

            # Success message
            typer.secho(
                f"\n✓ Successfully loaded {total_records:,} records",
                fg=typer.colors.GREEN,
                bold=True,
            )
            typer.secho(
                f"  Database operation completed in {total_batches} batch(es)",
                fg=typer.colors.GREEN,
            )

        except Exception:
            session.rollback()
            session.close()
            engine.dispose()
            raise

    except FileNotFoundError as e:
        logger.error("File not found: {}", str(e))
        typer.secho(
            f"✗ File not found: {csv_file}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    except ValueError as e:
        logger.error("Validation error: {}", str(e))
        typer.secho(
            f"✗ CSV validation failed: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    except Exception as e:
        logger.error("Failed to load CSV: {}", str(e))
        typer.secho(
            f"✗ Failed to load CSV: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


@app.command()
def geocode(
    batch_size: int | None = typer.Option(
        None,
        "--batch-size",
        "-b",
        help="Records per API call (max 10000)",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-l",
        help="Total records to process",
    ),
    retry_failed: bool = typer.Option(
        False,
        "--retry-failed",
        help="Retry previously failed records",
    ),
) -> None:
    """Geocode voter addresses using US Census Batch Geocoder."""
    logger.info(
        "geocode command called with batch_size={}, limit={}, retry_failed={}",
        batch_size,
        limit,
        retry_failed,
    )

    settings = get_settings()

    # Use default batch size if not specified
    if batch_size is None:
        batch_size = settings.default_batch_size
        logger.debug("Using default batch size: {}", batch_size)

    # Validate batch size
    if batch_size > 10000:
        typer.secho(
            "Error: batch_size cannot exceed 10000 (Census API limit)",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    try:
        # Get database connection
        engine = get_engine(settings)
        session = get_session(engine)

        try:
            # Import processing module
            from vote_match.processing import process_geocoding

            # Process geocoding with progress indication
            typer.echo("Starting geocoding process...")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=False,
            ) as progress:
                task = progress.add_task("Geocoding addresses...", total=None)

                # Process geocoding
                stats = process_geocoding(
                    session=session,
                    settings=settings,
                    batch_size=batch_size,
                    limit=limit,
                    retry_failed=retry_failed,
                )

                progress.update(task, completed=True)

            # Display results
            from rich.table import Table
            from rich.console import Console

            console = Console()

            table = Table(title="Geocoding Results", show_header=True, header_style="bold magenta")
            table.add_column("Status", style="cyan")
            table.add_column("Count", justify="right", style="green")
            table.add_column("Percentage", justify="right", style="yellow")

            total = stats["total_processed"]
            if total > 0:
                table.add_row(
                    "Matched",
                    str(stats["matched"]),
                    f"{stats['matched'] / total * 100:.1f}%",
                )
                table.add_row(
                    "No Match",
                    str(stats["no_match"]),
                    f"{stats['no_match'] / total * 100:.1f}%",
                )
                table.add_row(
                    "Failed",
                    str(stats["failed"]),
                    f"{stats['failed'] / total * 100:.1f}%",
                )
                table.add_row(
                    "Total",
                    str(total),
                    "100.0%",
                    style="bold",
                )
            else:
                table.add_row("No records processed", "0", "0.0%")

            console.print(table)

            # Success message
            if total > 0:
                typer.secho(
                    f"\n✓ Successfully processed {total:,} records",
                    fg=typer.colors.GREEN,
                    bold=True,
                )
                if stats["matched"] > 0:
                    typer.secho(
                        f"  {stats['matched']:,} addresses geocoded successfully",
                        fg=typer.colors.GREEN,
                    )
                if stats["no_match"] > 0:
                    typer.secho(
                        f"  {stats['no_match']:,} addresses could not be geocoded",
                        fg=typer.colors.YELLOW,
                    )
                if stats["failed"] > 0:
                    typer.secho(
                        f"  {stats['failed']:,} records failed",
                        fg=typer.colors.RED,
                    )
            else:
                typer.secho(
                    "No pending records to geocode",
                    fg=typer.colors.YELLOW,
                )

        finally:
            session.close()
            engine.dispose()

    except Exception as e:
        logger.error("Geocoding failed: {}", str(e))
        typer.secho(
            f"✗ Geocoding failed: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


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
