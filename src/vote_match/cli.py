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
        help="Retry previously failed records (API/batch errors)",
    ),
    retry_no_match: bool = typer.Option(
        False,
        "--retry-no-match",
        help="Retry records with no geocoding match",
    ),
) -> None:
    """Geocode voter addresses using US Census Batch Geocoder."""
    logger.info(
        "geocode command called with batch_size={}, limit={}, retry_failed={}, retry_no_match={}",
        batch_size,
        limit,
        retry_failed,
        retry_no_match,
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
                    retry_no_match=retry_no_match,
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
def validate_usps(
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-l",
        help="Total records to validate",
    ),
    retry_failed: bool = typer.Option(
        False,
        "--retry-failed",
        help="Retry previously failed validations",
    ),
) -> None:
    """Validate voter addresses using USPS Address Validation API."""
    logger.info(
        "validate-usps command called with limit={}, retry_failed={}",
        limit,
        retry_failed,
    )

    settings = get_settings()

    # Check that USPS credentials are configured
    if not settings.usps_client_id or not settings.usps_client_secret:
        typer.secho(
            "Error: USPS API credentials not configured",
            fg=typer.colors.RED,
            bold=True,
        )
        typer.secho(
            "Please set VOTE_MATCH_USPS_CLIENT_ID and VOTE_MATCH_USPS_CLIENT_SECRET",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)

    try:
        # Get database connection
        engine = get_engine(settings)
        session = get_session(engine)

        try:
            # Import processing module
            from vote_match.processing import process_usps_validation

            # Process USPS validation with progress indication
            typer.echo("Starting USPS validation process...")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=False,
            ) as progress:
                task = progress.add_task("Validating addresses...", total=None)

                # Process validation
                stats = process_usps_validation(
                    session=session,
                    settings=settings,
                    limit=limit,
                    retry_failed=retry_failed,
                )

                progress.update(task, completed=True)

            # Display results
            from rich.table import Table
            from rich.console import Console

            console = Console()

            table = Table(
                title="USPS Validation Results", show_header=True, header_style="bold magenta"
            )
            table.add_column("Status", style="cyan")
            table.add_column("Count", justify="right", style="green")
            table.add_column("Percentage", justify="right", style="yellow")

            total = stats["total_processed"]
            if total > 0:
                table.add_row(
                    "Validated (Matched as-is)",
                    str(stats["validated"]),
                    f"{stats['validated'] / total * 100:.1f}%",
                )
                table.add_row(
                    "Corrected (USPS updated)",
                    str(stats["corrected"]),
                    f"{stats['corrected'] / total * 100:.1f}%",
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
                if stats["validated"] > 0:
                    typer.secho(
                        f"  {stats['validated']:,} addresses validated as-is",
                        fg=typer.colors.GREEN,
                    )
                if stats["corrected"] > 0:
                    typer.secho(
                        f"  {stats['corrected']:,} addresses corrected by USPS",
                        fg=typer.colors.GREEN,
                    )
                if stats["failed"] > 0:
                    typer.secho(
                        f"  {stats['failed']:,} records failed validation",
                        fg=typer.colors.RED,
                    )
            else:
                typer.secho(
                    "No pending records to validate",
                    fg=typer.colors.YELLOW,
                )

        finally:
            session.close()
            engine.dispose()

    except Exception as e:
        logger.error("USPS validation failed: {}", str(e))
        typer.secho(
            f"✗ USPS validation failed: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


@app.command()
def status() -> None:
    """Display status of voter records (loaded, geocoded, matched)."""
    logger.info("status command called")

    settings = get_settings()

    try:
        # Get database connection
        engine = get_engine(settings)
        session = get_session(engine)

        try:
            from sqlalchemy import select, func, case
            from rich.console import Console
            from rich.table import Table

            console = Console()

            # Query total count
            total_count = session.execute(select(func.count()).select_from(Voter)).scalar()

            if total_count == 0:
                typer.secho(
                    "No voter records in database",
                    fg=typer.colors.YELLOW,
                )
                typer.secho(
                    "Use 'vote-match load-csv <file>' to import voter data",
                    fg=typer.colors.YELLOW,
                )
                return

            # Query counts by geocode status
            status_stmt = select(
                Voter.geocode_status,
                func.count().label("count"),
            ).group_by(Voter.geocode_status)
            status_results = session.execute(status_stmt).all()

            # Build status counts dictionary
            status_counts = {}
            for status, count in status_results:
                if status is None:
                    status_counts["pending"] = count
                else:
                    status_counts[status] = count

            # Calculate individual counts
            pending_count = status_counts.get("pending", 0)
            matched_count = status_counts.get("matched", 0)
            no_match_count = status_counts.get("no_match", 0)
            failed_count = status_counts.get("failed", 0)

            # Display title
            console.print("\n[bold cyan]Voter Record Status[/bold cyan]\n")

            # Create overall statistics table
            overall_table = Table(
                title="Overall Statistics", show_header=True, header_style="bold magenta"
            )
            overall_table.add_column("Status", style="cyan")
            overall_table.add_column("Count", justify="right", style="green")
            overall_table.add_column("Percent", justify="right")

            # Add rows with formatted numbers
            overall_table.add_row(
                "Total",
                f"{total_count:,}",
                "100.0%",
                style="bold",
            )
            overall_table.add_row(
                "Pending",
                f"{pending_count:,}",
                f"{pending_count / total_count * 100:.1f}%" if total_count > 0 else "0.0%",
            )
            overall_table.add_row(
                "Matched",
                f"{matched_count:,}",
                f"{matched_count / total_count * 100:.1f}%" if total_count > 0 else "0.0%",
            )
            overall_table.add_row(
                "No Match",
                f"{no_match_count:,}",
                f"{no_match_count / total_count * 100:.1f}%" if total_count > 0 else "0.0%",
            )
            overall_table.add_row(
                "Failed",
                f"{failed_count:,}",
                f"{failed_count / total_count * 100:.1f}%" if total_count > 0 else "0.0%",
            )

            console.print(overall_table)
            console.print()

            # Query county breakdown
            county_stmt = (
                select(
                    Voter.county,
                    func.count().label("total"),
                    func.sum(case((Voter.geocode_status == "matched", 1), else_=0)).label(
                        "matched"
                    ),
                )
                .group_by(Voter.county)
                .order_by(Voter.county)
            )
            county_results = session.execute(county_stmt).all()

            # Create county breakdown table
            if county_results:
                county_table = Table(
                    title="By County", show_header=True, header_style="bold magenta"
                )
                county_table.add_column("County", style="cyan")
                county_table.add_column("Total", justify="right", style="green")
                county_table.add_column("Matched", justify="right", style="green")
                county_table.add_column("Match %", justify="right")

                for county, total, matched in county_results:
                    county_name = county if county else "(Unknown)"
                    match_pct = (matched / total * 100) if total > 0 else 0.0
                    county_table.add_row(
                        county_name,
                        f"{total:,}",
                        f"{matched:,}",
                        f"{match_pct:.1f}%",
                    )

                console.print(county_table)
                console.print()

            # Query USPS validation status counts
            usps_stmt = select(
                Voter.usps_validation_status,
                func.count().label("count"),
            ).group_by(Voter.usps_validation_status)
            usps_results = session.execute(usps_stmt).all()

            # Build USPS status counts dictionary
            usps_status_counts = {}
            for status, count in usps_results:
                if status is None:
                    usps_status_counts["pending"] = count
                else:
                    usps_status_counts[status] = count

            # Only display USPS table if there's any USPS data
            if usps_status_counts:
                usps_pending = usps_status_counts.get("pending", 0)
                usps_validated = usps_status_counts.get("validated", 0)
                usps_corrected = usps_status_counts.get("corrected", 0)
                usps_failed = usps_status_counts.get("failed", 0)
                usps_total = usps_pending + usps_validated + usps_corrected + usps_failed

                usps_table = Table(
                    title="USPS Validation Status", show_header=True, header_style="bold magenta"
                )
                usps_table.add_column("Status", style="cyan")
                usps_table.add_column("Count", justify="right", style="green")
                usps_table.add_column("Percent", justify="right")

                usps_table.add_row(
                    "Pending",
                    f"{usps_pending:,}",
                    f"{usps_pending / usps_total * 100:.1f}%" if usps_total > 0 else "0.0%",
                )
                usps_table.add_row(
                    "Validated (as-is)",
                    f"{usps_validated:,}",
                    f"{usps_validated / usps_total * 100:.1f}%" if usps_total > 0 else "0.0%",
                )
                usps_table.add_row(
                    "Corrected",
                    f"{usps_corrected:,}",
                    f"{usps_corrected / usps_total * 100:.1f}%" if usps_total > 0 else "0.0%",
                )
                usps_table.add_row(
                    "Failed",
                    f"{usps_failed:,}",
                    f"{usps_failed / usps_total * 100:.1f}%" if usps_total > 0 else "0.0%",
                )

                console.print(usps_table)
                console.print()

        finally:
            session.close()
            engine.dispose()

    except Exception as e:
        logger.error("Failed to get status: {}", str(e))
        typer.secho(
            f"✗ Failed to get status: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


@app.command()
def export(
    output: Path = typer.Argument(..., help="Output file path"),
    format: str = typer.Option(
        "csv",
        "--format",
        "-f",
        help="Output format: csv or geojson",
    ),
    matched_only: bool = typer.Option(
        False,
        "--matched-only",
        help="Export only geocoded records",
    ),
) -> None:
    """Export voter records to CSV or GeoJSON."""
    logger.info(
        "export command called with output: {}, format: {}, matched_only: {}",
        output,
        format,
        matched_only,
    )

    # Validate format
    if format not in ["csv", "geojson"]:
        typer.secho(
            f"✗ Invalid format: {format}. Must be 'csv' or 'geojson'",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    # Validate output directory exists
    output_dir = output.parent
    if not output_dir.exists():
        typer.secho(
            f"✗ Output directory does not exist: {output_dir}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    settings = get_settings()

    try:
        # Get database connection
        engine = get_engine(settings)
        session = get_session(engine)

        try:
            from sqlalchemy import select

            # Build query
            query = select(Voter)
            if matched_only:
                query = query.filter(Voter.geocode_status == "matched")

            # Execute query with progress
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=False,
            ) as progress:
                task = progress.add_task("Querying database...", total=None)
                voters = session.execute(query).scalars().all()
                progress.update(task, completed=True)

            # Check if we have records
            if not voters:
                typer.secho(
                    "No records found to export",
                    fg=typer.colors.YELLOW,
                )
                return

            logger.info("Retrieved {} voters for export", len(voters))

            # Export based on format
            if format == "csv":
                _export_csv(voters, output)
            elif format == "geojson":
                _export_geojson(voters, output)

            # Success message
            typer.secho(
                f"\n✓ Successfully exported {len(voters):,} records to {output}",
                fg=typer.colors.GREEN,
                bold=True,
            )

        finally:
            session.close()
            engine.dispose()

    except Exception as e:
        logger.error("Export failed: {}", str(e))
        typer.secho(
            f"✗ Export failed: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


def _export_csv(voters: list[Voter], output: Path) -> None:
    """
    Export voters to CSV format.

    Args:
        voters: List of Voter objects to export
        output: Output file path
    """
    import pandas as pd

    logger.info("Exporting {} voters to CSV: {}", len(voters), output)

    # Convert voters to dictionaries
    records = []
    for voter in voters:
        # Get all attributes except SQLAlchemy internal state
        record = {}
        for key in voter.__mapper__.c.keys():
            value = getattr(voter, key)
            # Convert geometry to WKT string if present
            if key == "geom" and value is not None:
                # Skip geometry column for CSV
                continue
            record[key] = value
        records.append(record)

    # Create DataFrame and write to CSV
    df = pd.DataFrame(records)
    df.to_csv(output, index=False)

    logger.info("CSV export complete: {}", output)


def _export_geojson(voters: list[Voter], output: Path) -> None:
    """
    Export voters to GeoJSON format.

    Args:
        voters: List of Voter objects to export
        output: Output file path
    """
    import json

    logger.info("Exporting {} voters to GeoJSON: {}", len(voters), output)

    # Build features list
    features = []
    skipped = 0

    for voter in voters:
        # Only include records with valid coordinates
        if voter.geocode_longitude is None or voter.geocode_latitude is None:
            skipped += 1
            continue

        # Build properties dictionary (all voter fields except geom)
        properties = {}
        for key in voter.__mapper__.c.keys():
            if key == "geom":
                continue
            value = getattr(voter, key)
            properties[key] = value

        # Build feature
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [voter.geocode_longitude, voter.geocode_latitude],
            },
            "properties": properties,
        }
        features.append(feature)

    # Warn if records were skipped
    if skipped > 0:
        typer.secho(
            f"Warning: Skipped {skipped:,} records without valid coordinates",
            fg=typer.colors.YELLOW,
        )
        logger.warning("Skipped {} records without coordinates", skipped)

    # Build GeoJSON FeatureCollection
    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    # Write to file
    with open(output, "w") as f:
        json.dump(geojson, f, indent=2)

    logger.info("GeoJSON export complete: {} features written to {}", len(features), output)


if __name__ == "__main__":
    app()
