"""Command-line interface for Vote Match using Typer."""

from pathlib import Path

import typer
from loguru import logger
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.table import Table
from sqlalchemy import delete, select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from alembic import command as alembic_command

from vote_match.config import Settings, get_settings
from vote_match.database import init_database, get_engine, get_session
from vote_match.logging import setup_logging
from vote_match.csv_reader import read_voter_csv, dataframe_to_dicts
from vote_match.models import (
    DISTRICT_TYPES,
    CountyCommissionDistrict,
    DistrictBoundary,
    GeocodeResult,
    Voter,
)
from vote_match.migrations import (
    create_migration,
    upgrade_database,
    downgrade_database,
    show_current_revision,
    show_history,
    get_alembic_config,
)

console = Console()

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
        help="Drop existing tables and migration history before creating new ones",
    ),
    skip_migrations: bool = typer.Option(
        False,
        "--skip-migrations",
        help="Skip running migrations (PostGIS extension only)",
    ),
) -> None:
    """Initialize the PostGIS database schema."""
    logger.info("init-db command called with drop={}, skip_migrations={}", drop, skip_migrations)

    settings = get_settings()

    try:
        if drop:
            typer.secho(
                "WARNING: This will drop all existing tables and migration history!",
                fg=typer.colors.RED,
                bold=True,
            )
            confirm = typer.confirm("Are you sure you want to continue?")
            if not confirm:
                typer.secho("Operation cancelled", fg=typer.colors.YELLOW)
                raise typer.Abort()

        init_database(drop_tables=drop, settings=settings, run_migrations=not skip_migrations)

        typer.secho(
            "✓ Database initialized successfully",
            fg=typer.colors.GREEN,
            bold=True,
        )

        if drop:
            typer.secho(
                "  All tables and migration history were dropped and recreated",
                fg=typer.colors.YELLOW,
            )

        if skip_migrations:
            typer.secho(
                "  PostGIS extension and tables created (migrations skipped)",
                fg=typer.colors.GREEN,
            )
            typer.secho(
                "  Run 'vote-match db-upgrade' to apply migrations",
                fg=typer.colors.CYAN,
            )
        else:
            typer.secho(
                "  PostGIS extension created and migrations applied",
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
def db_migrate(
    message: str = typer.Option(
        ...,
        "--message",
        "-m",
        prompt="Migration message",
        help="Description of the migration",
    ),
) -> None:
    """Create a new database migration from model changes."""
    logger.info("db-migrate command called with message: {}", message)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=False,
        ) as progress:
            task = progress.add_task("Creating migration...", total=None)
            create_migration(message, autogenerate=True)
            progress.update(task, completed=True)

        typer.secho(
            "✓ Migration created successfully",
            fg=typer.colors.GREEN,
            bold=True,
        )
        typer.secho(
            "  Please review the migration file in alembic/versions/",
            fg=typer.colors.YELLOW,
        )
        typer.secho(
            "  Then run 'vote-match db-upgrade' to apply the migration",
            fg=typer.colors.CYAN,
        )

    except Exception as e:
        logger.error("Failed to create migration: {}", str(e))
        typer.secho(
            f"✗ Migration creation failed: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


@app.command()
def db_upgrade(
    revision: str = typer.Argument("head", help="Target revision (default: head)"),
) -> None:
    """Apply database migrations."""
    logger.info("db-upgrade command called with revision: {}", revision)

    try:
        # Show current revision before upgrade
        current = show_current_revision()
        if current:
            typer.echo(f"Current revision: {current}")
        else:
            typer.echo("Current revision: None (no migrations applied)")

        # Apply migrations
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=False,
        ) as progress:
            task = progress.add_task("Applying migrations...", total=None)
            upgrade_database(revision)
            progress.update(task, completed=True)

        # Show new revision
        new_current = show_current_revision()
        typer.secho(
            f"✓ Database upgraded successfully to: {new_current}",
            fg=typer.colors.GREEN,
            bold=True,
        )

    except Exception as e:
        logger.error("Failed to upgrade database: {}", str(e))
        typer.secho(
            f"✗ Database upgrade failed: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


@app.command()
def db_downgrade(
    revision: str = typer.Argument(..., help="Target revision to downgrade to"),
) -> None:
    """Rollback database migrations."""
    logger.info("db-downgrade command called with revision: {}", revision)

    try:
        # Show current revision
        current = show_current_revision()
        if current:
            typer.echo(f"Current revision: {current}")
        else:
            typer.echo("Current revision: None (no migrations applied)")

        # Warning and confirmation
        typer.secho(
            "WARNING: This will rollback your database schema!",
            fg=typer.colors.RED,
            bold=True,
        )
        confirm = typer.confirm("Are you sure you want to continue?")
        if not confirm:
            typer.secho("Operation cancelled", fg=typer.colors.YELLOW)
            raise typer.Abort()

        # Perform downgrade
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=False,
        ) as progress:
            task = progress.add_task("Rolling back migrations...", total=None)
            downgrade_database(revision)
            progress.update(task, completed=True)

        # Show new revision
        new_current = show_current_revision()
        if new_current:
            typer.secho(
                f"✓ Database downgraded successfully to: {new_current}",
                fg=typer.colors.GREEN,
                bold=True,
            )
        else:
            typer.secho(
                "✓ Database downgraded successfully (no migrations applied)",
                fg=typer.colors.GREEN,
                bold=True,
            )

    except Exception as e:
        logger.error("Failed to downgrade database: {}", str(e))
        typer.secho(
            f"✗ Database downgrade failed: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


@app.command()
def db_current() -> None:
    """Show current database migration revision."""
    logger.info("db-current command called")

    try:
        current = show_current_revision()

        if current is None:
            typer.secho(
                "No migrations applied to database",
                fg=typer.colors.YELLOW,
            )
            typer.secho(
                "Run 'vote-match db-upgrade' to apply migrations",
                fg=typer.colors.CYAN,
            )
        else:
            typer.secho(
                f"Current revision: {current}",
                fg=typer.colors.GREEN,
                bold=True,
            )

    except Exception as e:
        logger.error("Failed to get current revision: {}", str(e))
        typer.secho(
            f"✗ Failed to get current revision: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


@app.command()
def db_history() -> None:
    """Show database migration history."""
    logger.info("db-history command called")

    try:
        from rich.table import Table
        from rich.console import Console

        console = Console()

        # Get migration history
        history = show_history()

        # Create table
        table = Table(
            title="Migration History",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Revision", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Status", style="green")

        # Add rows (newest first)
        for revision, description, is_current in reversed(history):
            status = "✓ current" if is_current else ""
            table.add_row(revision[:12], description, status)

        console.print(table)

    except Exception as e:
        logger.error("Failed to get migration history: {}", str(e))
        typer.secho(
            f"✗ Failed to get migration history: {str(e)}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


@app.command()
def db_stamp(
    revision: str = typer.Argument("head", help="Revision to stamp (default: head)"),
) -> None:
    """Stamp the database with a specific migration revision without running migrations."""
    logger.info("db-stamp command called with revision: {}", revision)

    try:
        # Warning and confirmation
        typer.secho(
            "WARNING: This will mark migrations as applied without running them!",
            fg=typer.colors.RED,
            bold=True,
        )
        typer.secho(
            "Only use this for existing databases that already have the schema.",
            fg=typer.colors.YELLOW,
        )
        confirm = typer.confirm("Are you sure you want to continue?")
        if not confirm:
            typer.secho("Operation cancelled", fg=typer.colors.YELLOW)
            raise typer.Abort()

        # Stamp the database
        logger.info("Stamping database with revision: {}", revision)
        alembic_command.stamp(get_alembic_config(), revision)

        typer.secho(
            f"✓ Database stamped successfully with revision: {revision}",
            fg=typer.colors.GREEN,
            bold=True,
        )
        typer.secho(
            "Run 'vote-match db-current' to verify",
            fg=typer.colors.CYAN,
        )

    except Exception as e:
        logger.error("Failed to stamp database: {}", str(e))
        typer.secho(
            f"✗ Database stamp failed: {str(e)}",
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
    service: str | None = typer.Option(
        None,
        "--service",
        "-s",
        help="Geocoding service to use (default: census). Use 'list' to see available services",
    ),
    batch_size: int | None = typer.Option(
        None,
        "--batch-size",
        "-b",
        help="Records per batch",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-l",
        help="Total records to process",
    ),
    only_unmatched: bool | None = typer.Option(
        None,
        "--only-unmatched/--all",
        help="Process only no_match records from previous attempts (default: True for non-Census, False for Census)",
    ),
    retry_failed: bool = typer.Option(
        False,
        "--retry-failed",
        help="Retry previously failed records",
    ),
) -> None:
    """Geocode voter addresses using specified service.

    Cascading Strategy:
    - Census (default): Processes all ungeocoded voters
    - Other services: Process only no_match records from previous attempts

    Examples:
        vote-match geocode                           # Use Census (default)
        vote-match geocode --service nominatim       # Use Nominatim
        vote-match geocode --service census --all    # Force Census to process all voters
    """
    # Import geocoding modules
    from vote_match.geocoding.registry import GeocodeServiceRegistry
    from vote_match.geocoding.services import census, nominatim  # noqa: F401 - ensure services are registered
    from vote_match.processing import process_geocoding_service

    settings = get_settings()

    # Handle 'list' command
    if service == "list":
        typer.echo("Available geocoding services:")
        for svc in GeocodeServiceRegistry.list_services():
            typer.echo(f"  - {svc}")
        return

    # Use default service if not specified
    service_name = service or settings.default_geocode_service

    # Get geocoding service to check for service-specific batch size
    try:
        geocoding_service = GeocodeServiceRegistry.get_service(service_name, settings)
    except ValueError as e:
        typer.secho(str(e), fg=typer.colors.RED, bold=True)
        typer.secho(
            "\nUse 'vote-match geocode --service list' to see available services",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)

    # Use default batch size if not specified
    # Priority: CLI flag > service-specific default > global default
    if batch_size is None:
        service_config = getattr(settings.geocode_services, service_name, None)
        if service_config and hasattr(service_config, "batch_size") and service_config.batch_size:
            batch_size = service_config.batch_size
        else:
            batch_size = settings.default_batch_size

    # Default behavior for only_unmatched
    # Census processes all ungeocoded voters, other services only process no_match
    if only_unmatched is None:
        only_unmatched = service_name != "census"

    logger.info(
        f"geocode command called with service={service_name}, batch_size={batch_size}, "
        f"limit={limit}, only_unmatched={only_unmatched}, retry_failed={retry_failed}"
    )

    try:
        # Get database connection
        engine = get_engine(settings)
        session = get_session(engine)

        try:
            # Display strategy info
            if only_unmatched:
                typer.echo(
                    "Strategy: Processing only no_match records from previous geocoding attempts"
                )
            else:
                typer.echo("Strategy: Processing all voters without geocoding results")

            typer.echo(f"Service: {geocoding_service.service_name}")
            typer.echo(f"Batch size: {batch_size}")
            if limit:
                typer.echo(f"Limit: {limit}")
            typer.echo("")

            # Process geocoding with progress indication
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=False,
            ) as progress:
                task = progress.add_task(f"Geocoding with {service_name}...", total=None)

                # Process geocoding
                stats = process_geocoding_service(
                    session=session,
                    service=geocoding_service,
                    batch_size=batch_size,
                    limit=limit,
                    only_unmatched=only_unmatched,
                    retry_failed=retry_failed,
                )

                progress.update(task, completed=True)

            # Display results
            from rich.console import Console
            from rich.table import Table

            console = Console()

            table = Table(
                title=f"Geocoding Results ({service_name})",
                show_header=True,
                header_style="bold magenta",
            )
            table.add_column("Status", style="cyan")
            table.add_column("Count", justify="right", style="green")
            table.add_column("Percentage", justify="right", style="yellow")

            total = stats["total"]
            if total > 0:
                for status in ["exact", "interpolated", "approximate", "no_match", "failed"]:
                    if stats[status] > 0:
                        table.add_row(
                            status.replace("_", " ").title(),
                            str(stats[status]),
                            f"{stats[status] / total * 100:.1f}%",
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
                successful = stats["exact"] + stats["interpolated"] + stats["approximate"]
                if successful > 0:
                    typer.secho(
                        f"  {successful:,} addresses geocoded successfully",
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
        logger.error(f"Geocoding failed: {e}")
        typer.secho(
            f"✗ Geocoding failed: {e}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)


@app.command()
def sync_geocode(
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-l",
        help="Maximum number of voters to process",
    ),
    force_update: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Update geometry even if already set",
    ),
    skip_legacy_fields: bool = typer.Option(
        False,
        "--skip-legacy-fields",
        help="Don't update legacy geocode_* fields",
    ),
) -> None:
    """Sync best geocoding results to Voter table for QGIS display.

    This command updates the Voter table's PostGIS geometry column (geom)
    with the best geocoding result from all services. Required for QGIS
    visualization and spatial operations.

    The best result is selected automatically based on quality:
    exact > interpolated > approximate > no_match > failed

    Examples:
        vote-match sync-geocode                    # Sync all voters without geometry
        vote-match sync-geocode --force            # Update all voters including those with geometry
        vote-match sync-geocode --limit 1000       # Process first 1000 voters
    """
    logger.info(
        f"sync-geocode command called with limit={limit}, force_update={force_update}, "
        f"skip_legacy_fields={skip_legacy_fields}"
    )

    settings = get_settings()

    try:
        # Get database connection
        engine = get_engine(settings)
        session = get_session(engine)

        try:
            from vote_match.processing import sync_best_geocode_to_voters

            # Display info
            if force_update:
                typer.echo("Strategy: Updating ALL voters (including those with existing geometry)")
            else:
                typer.echo("Strategy: Updating only voters without geometry")

            if limit:
                typer.echo(f"Limit: {limit}")
            typer.echo("")

            # Process sync with progress indication
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=False,
            ) as progress:
                task = progress.add_task("Syncing geocode results...", total=None)

                # Sync results
                stats = sync_best_geocode_to_voters(
                    session=session,
                    limit=limit,
                    force_update=force_update,
                    update_legacy_fields=not skip_legacy_fields,
                )

                progress.update(task, completed=True)

            # Display results
            from rich.console import Console
            from rich.table import Table

            console = Console()

            table = Table(
                title="Sync Results",
                show_header=True,
                header_style="bold magenta",
            )
            table.add_column("Status", style="cyan")
            table.add_column("Count", justify="right", style="green")

            table.add_row("Total Processed", str(stats["total_processed"]))
            table.add_row("Updated", str(stats["updated"]), style="green")
            table.add_row("Skipped (No Results)", str(stats["skipped_no_results"]), style="yellow")
            table.add_row("Skipped (No Coords)", str(stats["skipped_no_coords"]), style="yellow")
            if not force_update and stats["skipped_already_set"] > 0:
                table.add_row(
                    "Skipped (Already Set)", str(stats["skipped_already_set"]), style="yellow"
                )

            console.print(table)

            # Success message
            if stats["updated"] > 0:
                typer.secho(
                    f"\n✓ Successfully updated {stats['updated']:,} voter geometries",
                    fg=typer.colors.GREEN,
                    bold=True,
                )
                typer.secho(
                    "  Voters are now ready for QGIS visualization",
                    fg=typer.colors.GREEN,
                )
            else:
                typer.secho(
                    "No voters needed geometry updates",
                    fg=typer.colors.YELLOW,
                )

        finally:
            session.close()
            engine.dispose()

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        typer.secho(
            f"✗ Sync failed: {e}",
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

            # --- District Boundaries & Comparison Status ---
            from vote_match.processing import get_district_status

            district_info = get_district_status(session)
            if district_info:
                dist_table = Table(
                    title="District Tracking Status",
                    show_header=True,
                    header_style="bold magenta",
                )
                dist_table.add_column("District Type", style="cyan")
                dist_table.add_column("Boundaries", justify="right", style="green")
                dist_table.add_column("Compared", justify="right", style="green")
                dist_table.add_column("Matched", justify="right", style="green")
                dist_table.add_column("Mismatched", justify="right", style="yellow")
                dist_table.add_column("No Boundary", justify="right")
                dist_table.add_column("No Reg Value", justify="right")

                for dtype, info in district_info.items():
                    dist_table.add_row(
                        dtype,
                        f"{info['boundaries']:,}",
                        f"{info['voters_compared']:,}",
                        f"{info['matched']:,}",
                        f"{info['mismatched']:,}",
                        f"{info['no_district']:,}",
                        f"{info['no_registered']:,}",
                    )

                console.print(dist_table)
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
def delete_geocode_results(
    service: str | None = typer.Option(
        None,
        "--service",
        "-s",
        help="Delete results from specific service (e.g., census, nominatim)",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Delete only results with specific status (e.g., failed, no_match)",
    ),
    all_results: bool = typer.Option(
        False,
        "--all",
        help="Delete ALL geocoding results (requires confirmation)",
    ),
) -> None:
    """Delete geocoding results from the database.

    This is useful for retrying failed geocodes with the same service.

    Examples:
        vote-match delete-geocode-results --service census --status failed
        vote-match delete-geocode-results --status failed  # All services
        vote-match delete-geocode-results --service nominatim  # All statuses
    """
    logger.info(
        f"delete-geocode-results command called with service={service}, "
        f"status={status}, all_results={all_results}"
    )

    # Valid status values
    VALID_STATUSES = {"exact", "interpolated", "approximate", "no_match", "failed"}

    # Validate parameters - at least one must be provided
    if not service and not status and not all_results:
        typer.secho(
            "✗ Error: Must specify at least one of --service, --status, or --all",
            fg=typer.colors.RED,
            bold=True,
        )
        typer.secho(
            "\nExamples:",
            fg=typer.colors.YELLOW,
        )
        typer.secho(
            "  vote-match delete-geocode-results --service census --status failed",
            fg=typer.colors.CYAN,
        )
        typer.secho(
            "  vote-match delete-geocode-results --status failed",
            fg=typer.colors.CYAN,
        )
        raise typer.Exit(code=1)

    # Validate status value if provided
    if status and status not in VALID_STATUSES:
        typer.secho(
            f"✗ Error: Invalid status '{status}'",
            fg=typer.colors.RED,
            bold=True,
        )
        typer.secho(
            f"\nValid statuses: {', '.join(sorted(VALID_STATUSES))}",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)

    settings = get_settings()

    try:
        # Get database connection
        engine = get_engine(settings)
        session = get_session(engine)

        try:
            # Build conditions for the query
            conditions = []
            if service:
                conditions.append(GeocodeResult.service_name == service)
            if status:
                conditions.append(GeocodeResult.status == status)

            # Query for count BEFORE deletion
            count_query = select(func.count()).select_from(GeocodeResult)
            for condition in conditions:
                count_query = count_query.filter(condition)

            count = session.execute(count_query).scalar()

            # Check if any records match
            if count == 0:
                typer.secho(
                    "No matching records found to delete",
                    fg=typer.colors.YELLOW,
                )

                # Show what was searched for
                filters = []
                if service:
                    filters.append(f"service: {service}")
                if status:
                    filters.append(f"status: {status}")
                if all_results:
                    filters.append("all results")

                typer.secho(
                    f"Filters applied: {', '.join(filters)}",
                    fg=typer.colors.YELLOW,
                )
                return

            # Show what will be deleted and confirm
            typer.echo(f"\nRecords to delete: {count:,}")

            filters = []
            if service:
                filters.append(f"service: {service}")
            if status:
                filters.append(f"status: {status}")
            if all_results:
                filters.append("all results")

            typer.echo(f"Filters: {', '.join(filters)}")
            typer.echo("")

            typer.secho(
                "WARNING: This will permanently delete geocoding results!",
                fg=typer.colors.RED,
                bold=True,
            )

            confirm = typer.confirm("Are you sure you want to continue?")
            if not confirm:
                typer.secho("Operation cancelled", fg=typer.colors.YELLOW)
                raise typer.Abort()

            # Execute deletion
            delete_stmt = delete(GeocodeResult)
            for condition in conditions:
                delete_stmt = delete_stmt.where(condition)

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=False,
            ) as progress:
                task = progress.add_task("Deleting records...", total=None)
                result = session.execute(delete_stmt)
                session.commit()
                progress.update(task, completed=True)

            # Get the actual count of deleted rows
            deleted_count = result.rowcount

            # Display results
            from rich.console import Console
            from rich.table import Table

            console = Console()

            table = Table(
                title="Deletion Summary",
                show_header=True,
                header_style="bold magenta",
            )
            table.add_column("Attribute", style="cyan")
            table.add_column("Value", style="green")

            table.add_row("Records Deleted", f"{deleted_count:,}")
            if service:
                table.add_row("Service", service)
            if status:
                table.add_row("Status", status)

            console.print(table)

            # Success message
            typer.secho(
                f"\n✓ Successfully deleted {deleted_count:,} geocoding results",
                fg=typer.colors.GREEN,
                bold=True,
            )

            if status == "failed":
                typer.secho(
                    "\nYou can now retry geocoding with:",
                    fg=typer.colors.CYAN,
                )
                if service:
                    typer.secho(
                        f"  vote-match geocode --service {service} --only-unmatched --retry-failed",
                        fg=typer.colors.CYAN,
                    )
                else:
                    typer.secho(
                        "  vote-match geocode --service <name> --only-unmatched --retry-failed",
                        fg=typer.colors.CYAN,
                    )

        finally:
            session.close()
            engine.dispose()

    except typer.Abort:
        # User cancelled the operation - this is expected, not an error
        logger.info("Delete operation cancelled by user")
        raise typer.Exit(code=0)
    except Exception as e:
        logger.error(f"Failed to delete geocode results: {e}")
        typer.secho(
            f"✗ Failed to delete geocode results: {e}",
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
        help="Output format: csv, geojson, or leaflet",
    ),
    matched_only: bool = typer.Option(
        False,
        "--matched-only",
        help="Export only geocoded records",
    ),
    mismatch_only: bool = typer.Option(
        False,
        "--mismatch-only",
        help="Export only voters with district mismatches",
    ),
    district_type: list[str] | None = typer.Option(
        None,
        "--district-type",
        "-dt",
        help="Filter by specific district type(s) when using --mismatch-only. Can be repeated. Examples: state_senate, congressional, county_commission",
    ),
    exact_match_only: bool = typer.Option(
        False,
        "--exact-match-only",
        help="Export only voters with exact geocode matches",
    ),
    include_districts: bool = typer.Option(
        False,
        "--include-districts",
        help="Include district boundaries (leaflet format only)",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Map title (leaflet format only). If not specified, uses VOTE_MATCH_MAP_TITLE from .env",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        help="Limit number of records to export",
    ),
    county: str | None = typer.Option(
        None,
        "--county",
        help="Filter by county name (e.g., 'BIBB', 'FULTON')",
    ),
    upload_to_r2: bool = typer.Option(
        False,
        "--upload-to-r2",
        help="Upload map to Cloudflare R2 (leaflet format only)",
    ),
    redact_pii: bool = typer.Option(
        False,
        "--redact-pii",
        help="Redact voter PII (name, address, registration number) from map. Only shows location, district, and data quality info.",
    ),
    print_embed_code: bool = typer.Option(
        False,
        "--print-embed-code",
        "--embed",
        help="Print HTML iframe embed code after map generation (leaflet format only)",
    ),
) -> None:
    """Export voter records to CSV, GeoJSON, or interactive Leaflet map."""
    logger.info(
        "export command called with output: {}, format: {}, matched_only: {}, "
        "mismatch_only: {}, district_type: {}, exact_match_only: {}, include_districts: {}, title: {}, limit: {}, county: {}, upload_to_r2: {}, redact_pii: {}, print_embed_code: {}",
        output,
        format,
        matched_only,
        mismatch_only,
        district_type,
        exact_match_only,
        include_districts,
        title,
        limit,
        county,
        upload_to_r2,
        redact_pii,
        print_embed_code,
    )

    # Validate format
    if format not in ["csv", "geojson", "leaflet"]:
        typer.secho(
            f"✗ Invalid format: {format}. Must be 'csv', 'geojson', or 'leaflet'",
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
            # Handle leaflet format separately (uses different processing logic)
            if format == "leaflet":
                # Use map title from settings if not provided via CLI
                map_title = title if title is not None else settings.map_title

                _export_leaflet(
                    session=session,
                    output=output,
                    title=map_title,
                    limit=limit,
                    include_districts=include_districts,
                    matched_only=matched_only,
                    mismatch_only=mismatch_only,
                    exact_match_only=exact_match_only,
                    settings=settings,
                    upload_to_r2=upload_to_r2,
                    redact_pii=redact_pii,
                    print_embed_code=print_embed_code,
                    district_type=district_type,
                    county=county,
                )
                return

            # For CSV and GeoJSON formats, query voters
            from sqlalchemy import select

            # Build query
            query = select(Voter)

            # Apply filters (can be combined)
            if matched_only:
                query = query.filter(
                    Voter.geocode_status.in_(["exact", "interpolated", "approximate"])
                )

            if mismatch_only:
                if district_type:
                    # Filter by specific district type(s) using JOIN
                    from vote_match.models import VoterDistrictAssignment

                    query = (
                        query.join(
                            VoterDistrictAssignment,
                            Voter.voter_registration_number == VoterDistrictAssignment.voter_id,
                        )
                        .filter(
                            VoterDistrictAssignment.district_type.in_(district_type),
                            VoterDistrictAssignment.is_mismatch,
                        )
                        .distinct()
                    )  # Avoid duplicates if multiple district types
                else:
                    # No specific type: use legacy field (any mismatch)
                    query = query.filter(Voter.district_mismatch)

            if exact_match_only:
                query = query.filter(Voter.geocode_match_type == "exact")

            if county:
                # Normalize county name to uppercase for consistent matching
                normalized_county = county.strip().upper()
                query = query.filter(Voter.county == normalized_county)

            if limit:
                query = query.limit(limit)

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


def _generate_iframe_embed_code(
    url: str,
    title: str,
    width: str = "100%",
    height: str = "600px",
) -> str:
    """
    Generate HTML iframe embed code for a map.

    Args:
        url: The URL to embed (R2 public URL or local file path)
        title: Map title for iframe accessibility
        width: CSS width value (default: "100%")
        height: CSS height value (default: "600px")

    Returns:
        Formatted HTML iframe code ready for embedding
    """
    # Escape any quotes in the title for HTML attribute safety
    safe_title = title.replace('"', "&quot;")

    iframe_code = f"""<iframe
  src="{url}"
  title="{safe_title}"
  width="{width}"
  height="{height}"
  style="border: 1px solid #ccc; border-radius: 4px;"
  allowfullscreen
  loading="lazy">
</iframe>"""

    return iframe_code


def _export_leaflet(
    session: Session,
    output: Path,
    title: str,
    limit: int | None,
    include_districts: bool,
    matched_only: bool,
    mismatch_only: bool,
    exact_match_only: bool,
    settings: Settings,
    upload_to_r2: bool = False,
    redact_pii: bool = False,
    print_embed_code: bool = False,
    district_type: list[str] | None = None,
    county: str | None = None,
) -> None:
    """
    Export voters to interactive Leaflet map HTML.

    Args:
        session: SQLAlchemy session
        output: Output file path
        title: Map title
        limit: Maximum number of voters to include
        include_districts: Whether to include district boundaries
        matched_only: If True, only include voters with successful geocoding
        mismatch_only: If True, only include voters with district mismatches
        exact_match_only: If True, only include voters with exact geocode matches
        settings: Application settings
        upload_to_r2: If True, upload the generated map to Cloudflare R2
        redact_pii: If True, exclude PII fields from voter data
        print_embed_code: If True, print HTML iframe embed code after generation
        district_type: List of district types to filter by (when mismatch_only is True)
        county: Filter by county name (normalized to uppercase)
    """
    from vote_match.processing import generate_leaflet_map

    logger.info("Generating Leaflet map: {}", output)

    # Determine output directory and HTML filename
    if output.is_dir():
        web_dir = output
        html_filename = "index.html"
    else:
        # If output is a file path, create a web folder in the same directory
        web_dir = output.parent / "web"
        html_filename = output.name  # Extract filename (e.g., "map.html")

    # Show progress
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=False,
    ) as progress:
        task = progress.add_task("Generating interactive map...", total=None)

        # Generate map with web folder structure
        index_path = generate_leaflet_map(
            session=session,
            title=title,
            limit=limit,
            include_districts=include_districts,
            matched_only=matched_only,
            mismatch_only=mismatch_only,
            exact_match_only=exact_match_only,
            output_path=web_dir,
            html_filename=html_filename,
            settings=settings,
            redact_pii=redact_pii,
            district_type=district_type[0] if district_type else None,
            county=county,
        )

        progress.update(task, completed=True)

    logger.info("Leaflet map export complete: {}", index_path)

    # Upload to R2 if requested
    r2_url = None
    if upload_to_r2:
        from vote_match.r2_storage import upload_to_r2 as r2_upload

        try:
            # Upload index.html, voters.geojson, and districts.geojson
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=False,
            ) as progress:
                task = progress.add_task("Uploading to Cloudflare R2...", total=None)

                # Upload all files in web directory
                web_dir = Path(index_path).parent
                for file_path in web_dir.glob("*"):
                    if file_path.is_file():
                        object_key = file_path.name
                        content_type = (
                            "text/html" if file_path.suffix == ".html" else "application/geo+json"
                        )
                        r2_upload(file_path, object_key, settings, content_type=content_type)
                        logger.info(f"Uploaded {file_path.name} to R2")

                # Construct the public URL for the HTML file
                if settings.r2_public_url:
                    base_url = settings.r2_public_url.rstrip("/")
                    if settings.r2_folder:
                        folder = settings.r2_folder.strip("/")
                        r2_url = f"{base_url}/{folder}/{html_filename}"
                    else:
                        r2_url = f"{base_url}/{html_filename}"

                progress.update(task, completed=True)

            if r2_url:
                logger.info("Map uploaded to R2: {}", r2_url)
            else:
                logger.warning("R2 upload completed but public URL not configured")
        except ValueError as e:
            logger.error("R2 upload error: {}", str(e))
            typer.secho(
                f"   Warning: R2 upload failed - {str(e)}",
                fg=typer.colors.YELLOW,
            )

    # Success message
    typer.secho(
        "\n✓ Successfully generated interactive map in web folder",
        fg=typer.colors.GREEN,
        bold=True,
    )

    # Additional info
    typer.secho(
        f"   Location: {Path(index_path).parent}",
        fg=typer.colors.BLUE,
    )

    if include_districts:
        typer.secho(
            "   Map includes district boundaries for visual mismatch detection",
            fg=typer.colors.BLUE,
        )

    if r2_url:
        typer.secho(
            f"   Map uploaded to R2: {r2_url}",
            fg=typer.colors.GREEN,
        )
    else:
        typer.secho(
            f"   Open {index_path} in a web browser to view the map",
            fg=typer.colors.BLUE,
        )

    # Print embed code if requested
    if print_embed_code:
        typer.secho("\n" + "=" * 70, fg=typer.colors.CYAN)
        typer.secho("HTML Embed Code", fg=typer.colors.CYAN, bold=True)
        typer.secho("=" * 70, fg=typer.colors.CYAN)

        if r2_url:
            # Use R2 public URL
            embed_code = _generate_iframe_embed_code(url=r2_url, title=title)
            typer.secho(
                f"\nYour map is publicly accessible at: {r2_url}",
                fg=typer.colors.GREEN,
            )
            typer.secho(
                "\nCopy and paste this code to embed the map in your website:\n",
                fg=typer.colors.BLUE,
            )
        else:
            # Local file - provide instructions
            embed_code = _generate_iframe_embed_code(url="YOUR_MAP_URL_HERE", title=title)
            typer.secho(
                "\nMap generated locally. To embed this map:",
                fg=typer.colors.YELLOW,
            )
            typer.secho(
                f"  1. Upload the contents of {Path(index_path).parent} to a web server",
                fg=typer.colors.BLUE,
            )
            typer.secho(
                f"  2. Replace 'YOUR_MAP_URL_HERE' with the public URL to {html_filename}",
                fg=typer.colors.BLUE,
            )
            typer.secho(
                "  3. Use the embed code below:\n",
                fg=typer.colors.BLUE,
            )

        # Print embed code with high contrast for easy copying
        typer.secho(embed_code, fg=typer.colors.WHITE, bg=typer.colors.BLACK)
        typer.secho("\n" + "=" * 70 + "\n", fg=typer.colors.CYAN)


@app.command()
def import_geojson(
    geojson_file: Path = typer.Argument(
        ...,
        help="Path to GeoJSON file containing district boundaries",
    ),
    district_type: str | None = typer.Option(
        None,
        "--district-type",
        "-t",
        help=(
            "Type of district boundaries being imported. "
            "Use 'list' to show all valid types. "
            "Required unless --legacy is used. "
            "Examples: congressional, state_senate, county_commission, school_board"
        ),
    ),
    clear: bool = typer.Option(
        False,
        "--clear",
        help="Clear existing boundaries for this district type before importing",
    ),
    id_property: str | None = typer.Option(
        None,
        "--id-property",
        help="GeoJSON property key containing district ID (auto-detected if omitted)",
    ),
    name_property: str | None = typer.Option(
        None,
        "--name-property",
        help="GeoJSON property key containing district name (auto-detected if omitted)",
    ),
    legacy: bool = typer.Option(
        False,
        "--legacy",
        help="Import into legacy county_commission_districts table (backward compat)",
    ),
) -> None:
    """Import district boundaries from a GeoJSON file.

    Supports all district types found in state voter roll data:
    congressional, state_senate, state_house, county_commission,
    school_board, city_council, judicial, fire, municipality, and more.

    Use --district-type list to see all valid types.

    The GeoJSON file should contain a FeatureCollection with district polygons.
    """
    # Validate: either legacy OR district_type must be provided
    if not legacy and district_type is None:
        typer.secho(
            "✗ Error: --district-type is required unless using --legacy",
            fg=typer.colors.RED,
            bold=True,
        )
        typer.echo("\nUse 'vote-match list-district-types' to see available types")
        raise typer.Exit(code=1)

    # Handle 'list' subcommand
    if district_type == "list":
        table = Table(title="Available District Types", header_style="bold magenta")
        table.add_column("Type Key", style="cyan")
        table.add_column("Voter Column", style="green")
        for key, col in sorted(DISTRICT_TYPES.items()):
            table.add_row(key, col)
        console.print()
        console.print(table)
        console.print()
        return

    logger.info(
        "import-geojson command called: file={}, type={}, legacy={}",
        geojson_file,
        district_type,
        legacy,
    )

    # --- Legacy path (unchanged behavior for county_commission_districts) ---
    if legacy:
        settings = get_settings()
        try:
            if not geojson_file.exists():
                typer.secho(
                    f"✗ GeoJSON file not found: {geojson_file}",
                    fg=typer.colors.RED,
                    bold=True,
                )
                raise typer.Exit(code=1)

            engine = get_engine(settings)
            session = get_session(engine)
            try:
                if clear:
                    count = session.query(CountyCommissionDistrict).count()
                    typer.secho(
                        f"WARNING: About to delete {count} existing legacy district records!",
                        fg=typer.colors.RED,
                        bold=True,
                    )
                    confirm = typer.confirm("Are you sure you want to continue?")
                    if not confirm:
                        typer.secho("Operation cancelled", fg=typer.colors.YELLOW)
                        raise typer.Abort()

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    transient=False,
                ) as progress:
                    task = progress.add_task("Importing districts (legacy)...", total=None)
                    from vote_match.processing import import_geojson_districts

                    result = import_geojson_districts(
                        session=session,
                        file_path=geojson_file,
                        clear_existing=clear,
                    )
                    progress.update(task, completed=True)

                table = Table(title="Legacy Import Results", header_style="bold magenta")
                table.add_column("Metric", style="cyan")
                table.add_column("Count", style="green", justify="right")
                table.add_row("Total Features", str(result["total"]))
                table.add_row("Successfully Imported", str(result["success"]))
                table.add_row("Skipped", str(result["skipped"]))
                table.add_row("Failed", str(result["failed"]))
                console.print()
                console.print(table)
                console.print()
                typer.secho(
                    f"✓ Legacy import complete: {result['success']} districts imported",
                    fg=typer.colors.GREEN,
                    bold=True,
                )
            finally:
                session.close()
                engine.dispose()
        except Exception as e:
            typer.secho(f"✗ Import failed: {e}", fg=typer.colors.RED, bold=True)
            logger.exception("import-geojson (legacy) failed: {}", e)
            raise typer.Exit(code=1)
        return

    # --- New generic path ---
    # After legacy path returns, district_type is guaranteed to be set
    assert district_type is not None  # Type narrowing for mypy

    if district_type not in DISTRICT_TYPES:
        typer.secho(
            f"✗ Unknown district type '{district_type}'. "
            f"Valid types: {', '.join(sorted(DISTRICT_TYPES))}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    settings = get_settings()

    try:
        if not geojson_file.exists():
            typer.secho(
                f"✗ GeoJSON file not found: {geojson_file}",
                fg=typer.colors.RED,
                bold=True,
            )
            raise typer.Exit(code=1)

        engine = get_engine(settings)
        session = get_session(engine)

        try:
            if clear:
                count = (
                    session.query(DistrictBoundary)
                    .filter(DistrictBoundary.district_type == district_type)
                    .count()
                )
                typer.secho(
                    f"WARNING: About to delete {count} existing '{district_type}' boundaries!",
                    fg=typer.colors.RED,
                    bold=True,
                )
                confirm = typer.confirm("Are you sure you want to continue?")
                if not confirm:
                    typer.secho("Operation cancelled", fg=typer.colors.YELLOW)
                    raise typer.Abort()

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=False,
            ) as progress:
                task = progress.add_task(f"Importing {district_type} boundaries...", total=None)

                from vote_match.processing import import_district_boundaries

                result = import_district_boundaries(
                    session=session,
                    file_path=geojson_file,
                    district_type=district_type,
                    clear_existing=clear,
                    id_property=id_property,
                    name_property=name_property,
                )

                progress.update(task, completed=True)

            table = Table(title=f"Import Results ({district_type})", header_style="bold magenta")
            table.add_column("Metric", style="cyan")
            table.add_column("Count", style="green", justify="right")
            table.add_row("Total Features", str(result["total"]))
            table.add_row("Successfully Imported", str(result["success"]))
            table.add_row("Skipped", str(result["skipped"]))
            table.add_row("Failed", str(result["failed"]))

            console.print()
            console.print(table)
            console.print()

            typer.secho(
                f"✓ Import complete: {result['success']} {district_type} boundaries imported",
                fg=typer.colors.GREEN,
                bold=True,
            )

            logger.info("import-geojson completed successfully")

        finally:
            session.close()
            engine.dispose()

    except FileNotFoundError as e:
        typer.secho(f"✗ File error: {e}", fg=typer.colors.RED, bold=True)
        logger.error("File not found: {}", e)
        raise typer.Exit(code=1)
    except ValueError as e:
        typer.secho(f"✗ Invalid GeoJSON: {e}", fg=typer.colors.RED, bold=True)
        logger.error("Invalid GeoJSON: {}", e)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.secho(f"✗ Import failed: {e}", fg=typer.colors.RED, bold=True)
        logger.exception("import-geojson failed with error: {}", e)
        raise typer.Exit(code=1)


@app.command()
def list_district_types() -> None:
    """List all valid district types that can be imported and compared.

    Shows the mapping between district type keys (used in commands) and
    the corresponding voter registration columns.
    """
    table = Table(title="Available District Types", header_style="bold magenta")
    table.add_column("Type Key", style="cyan", no_wrap=True)
    table.add_column("Voter Column", style="green")
    table.add_column("Description", style="white", max_width=50)

    # Add descriptions for common types
    descriptions = {
        "congressional": "US Congressional Districts",
        "state_senate": "State Senate Districts",
        "state_house": "State House/Assembly Districts",
        "county_commission": "County Commission Districts",
        "school_board": "School Board Districts",
        "city_council": "City Council Districts",
        "judicial": "Judicial Districts",
        "county_precinct": "County Voting Precincts",
        "municipality": "City/Town Boundaries",
        "fire": "Fire Districts",
    }

    for key, col in sorted(DISTRICT_TYPES.items()):
        desc = descriptions.get(key, "")
        table.add_row(key, col, desc)

    console.print()
    console.print(table)
    console.print()
    console.print(
        "[dim]Use these type keys with:[/dim]\n"
        "  [cyan]vote-match import-geojson file.json --district-type <type>[/cyan]\n"
        "  [cyan]vote-match compare-districts --district-type <type>[/cyan]"
    )
    console.print()


@app.command()
def import_shapefiles(
    data_dir: Path = typer.Option(
        Path("data"),
        "--data-dir",
        "-d",
        help="Directory containing district ZIP files (default: ./data)",
    ),
    clear: bool = typer.Option(
        False,
        "--clear",
        help="Clear existing boundaries before importing (requires confirmation)",
    ),
    skip_existing: bool = typer.Option(
        True,
        "--skip-existing/--no-skip-existing",
        help="Skip files for district types that already have boundaries (default: True)",
    ),
) -> None:
    """Batch import all district shapefiles from the data directory.

    Automatically maps district ZIP files to their types based on filename:
    - congress-*.zip → congressional
    - senate-*.zip → state_senate
    - house-*.zip → state_house
    - bibbcc-*.zip → county_commission (Bibb County Commission)
    - bibbsb-*.zip → school_board (Bibb School Board)
    - gaprec-*.zip → county_precinct (GA Precincts)
    - psc-*.zip → psc (Public Service Commission)

    Example:
        vote-match import-shapefiles --data-dir data
        vote-match import-shapefiles --clear --no-skip-existing
    """
    logger.info(f"import-shapefiles command called with data_dir: {data_dir}")

    # Import processing function
    from vote_match.processing import import_district_boundaries

    # Filename prefix to district type mapping
    FILENAME_TO_DISTRICT_TYPE = {
        "congress": "congressional",
        "senate": "state_senate",
        "house": "state_house",
        "bibbcc": "county_commission",
        "bibbsb": "school_board",
        "gaprec": "county_precinct",
        "psc": "psc",
    }

    # Validate data directory
    if not data_dir.exists():
        typer.secho(
            f"✗ Error: Data directory not found: {data_dir}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    if not data_dir.is_dir():
        typer.secho(
            f"✗ Error: Not a directory: {data_dir}",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    # Find all ZIP files and map to district types
    zip_files = list(data_dir.glob("*.zip"))
    if not zip_files:
        typer.secho(
            f"✗ No ZIP files found in {data_dir}",
            fg=typer.colors.YELLOW,
            bold=True,
        )
        raise typer.Exit(code=1)

    # Build import plan
    import_plan: list[tuple[Path, str]] = []
    unmatched_files: list[Path] = []

    for zip_file in sorted(zip_files):
        # Skip checksum files
        if zip_file.suffix == ".txt" or ".sha512" in zip_file.name:
            continue

        matched = False
        filename_lower = zip_file.name.lower()

        for prefix, district_type in FILENAME_TO_DISTRICT_TYPE.items():
            if filename_lower.startswith(prefix):
                import_plan.append((zip_file, district_type))
                matched = True
                break

        if not matched:
            unmatched_files.append(zip_file)

    # Display import plan
    console.print("\n[bold cyan]Import Plan[/bold cyan]\n")

    if import_plan:
        plan_table = Table(show_header=True, header_style="bold magenta")
        plan_table.add_column("File", style="cyan")
        plan_table.add_column("District Type", style="green")

        for file_path, district_type in import_plan:
            plan_table.add_row(file_path.name, district_type)

        console.print(plan_table)
    else:
        typer.secho("✗ No matching files found to import", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    if unmatched_files:
        console.print("\n[yellow]Unmatched files (will be skipped):[/yellow]")
        for file_path in unmatched_files:
            console.print(f"  - {file_path.name}")

    console.print()

    # Get database connection
    settings = get_settings()
    engine = get_engine(settings)
    session = get_session(engine)

    try:
        # Check which district types already have boundaries
        existing_districts: set[str] = set()
        for _, district_type in import_plan:
            count = (
                session.query(DistrictBoundary)
                .filter(DistrictBoundary.district_type == district_type)
                .count()
            )
            if count > 0:
                existing_districts.add(district_type)

        # Handle clear option
        if clear:
            if existing_districts:
                typer.secho(
                    f"\n⚠ Warning: This will delete ALL existing boundaries for {len(existing_districts)} district types:\n",
                    fg=typer.colors.YELLOW,
                    bold=True,
                )
                for district_type in sorted(existing_districts):
                    count = (
                        session.query(DistrictBoundary)
                        .filter(DistrictBoundary.district_type == district_type)
                        .count()
                    )
                    typer.secho(f"  - {district_type}: {count} boundaries", fg=typer.colors.YELLOW)

                confirmed = typer.confirm("\nAre you sure you want to continue?", default=False)
                if not confirmed:
                    typer.secho("✗ Import cancelled", fg=typer.colors.YELLOW)
                    raise typer.Exit(code=0)

                # Clear all existing boundaries for types in import plan
                for _, district_type in import_plan:
                    session.query(DistrictBoundary).filter(
                        DistrictBoundary.district_type == district_type
                    ).delete()
                session.commit()
                typer.secho("✓ Cleared existing boundaries\n", fg=typer.colors.GREEN)
                existing_districts.clear()

        # Import each file
        results: list[tuple[str, str, dict[str, int]]] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for file_path, district_type in import_plan:
                # Skip if already exists and skip_existing is True
                if skip_existing and district_type in existing_districts:
                    task = progress.add_task(f"Skipping {district_type} (already exists)", total=1)
                    progress.update(task, advance=1)
                    results.append(
                        (
                            file_path.name,
                            district_type,
                            {"total": 0, "success": 0, "failed": 0, "skipped": 0},
                        )
                    )
                    logger.info(f"Skipped {district_type} - already exists")
                    continue

                # Import boundaries
                task = progress.add_task(f"Importing {district_type}...", total=None)

                try:
                    stats = import_district_boundaries(
                        session=session,
                        file_path=file_path,
                        district_type=district_type,
                        clear_existing=False,  # Already handled above if needed
                    )
                    results.append((file_path.name, district_type, stats))
                    progress.update(task, completed=1, total=1)
                    logger.info(
                        f"Imported {district_type}: {stats['success']} success, "
                        f"{stats['failed']} failed, {stats['skipped']} skipped"
                    )
                except Exception as e:
                    progress.update(task, completed=1, total=1)
                    logger.error(f"Failed to import {district_type}: {e}")
                    results.append(
                        (
                            file_path.name,
                            district_type,
                            {"total": 0, "success": 0, "failed": 1, "skipped": 0},
                        )
                    )

        # Display results summary
        console.print("\n[bold cyan]Import Summary[/bold cyan]\n")

        summary_table = Table(show_header=True, header_style="bold magenta")
        summary_table.add_column("File", style="cyan")
        summary_table.add_column("District Type", style="white")
        summary_table.add_column("Total", justify="right", style="blue")
        summary_table.add_column("Success", justify="right", style="green")
        summary_table.add_column("Failed", justify="right", style="red")
        summary_table.add_column("Skipped", justify="right", style="yellow")

        total_all = 0
        success_all = 0
        failed_all = 0
        skipped_all = 0

        for filename, district_type, stats in results:
            total_all += stats["total"]
            success_all += stats["success"]
            failed_all += stats["failed"]
            skipped_all += stats["skipped"]

            # Show status indicator
            if stats["total"] == 0 and stats["failed"] == 0:
                # Skipped because already exists
                status = "⊘"
            elif stats["failed"] > 0:
                status = "✗"
            elif stats["success"] > 0:
                status = "✓"
            else:
                status = "-"

            summary_table.add_row(
                f"{status} {filename}",
                district_type,
                str(stats["total"]),
                str(stats["success"]),
                str(stats["failed"]),
                str(stats["skipped"]),
            )

        # Add totals row
        summary_table.add_row(
            "[bold]TOTAL[/bold]",
            "",
            f"[bold]{total_all}[/bold]",
            f"[bold]{success_all}[/bold]",
            f"[bold]{failed_all}[/bold]",
            f"[bold]{skipped_all}[/bold]",
        )

        console.print(summary_table)
        console.print()

        # Final status message
        if failed_all > 0:
            typer.secho(
                f"⚠ Import completed with {failed_all} failures",
                fg=typer.colors.YELLOW,
                bold=True,
            )
        elif success_all > 0:
            typer.secho(
                f"✓ Successfully imported {success_all} district boundaries",
                fg=typer.colors.GREEN,
                bold=True,
            )
        else:
            typer.secho(
                "✓ All districts already imported (use --no-skip-existing to re-import)",
                fg=typer.colors.GREEN,
            )

        session.close()
        engine.dispose()

    except Exception as e:
        session.close()
        engine.dispose()
        logger.exception("import-shapefiles failed with error: {}", e)
        typer.secho(f"✗ Error: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=1)


@app.command(name="link-districts-to-counties")
def link_districts_to_counties(
    csv_file: Path | None = typer.Argument(
        None,
        help="Path to CSV file mapping counties to districts (e.g., counties-by-districts-2023.csv)",
        exists=True,
        dir_okay=False,
        resolve_path=True,
    ),
    spatial: bool = typer.Option(
        False,
        "--spatial",
        help="Use PostGIS spatial joins instead of CSV mapping",
    ),
    district_type: str | None = typer.Option(
        None,
        "--district-type",
        "-t",
        help="Specific district type to process (default: all)",
    ),
    state_fips: str | None = typer.Option(
        None,
        "--state-fips",
        help="State FIPS code for spatial filtering (e.g., '13' for Georgia)",
    ),
    validate: bool = typer.Option(
        False,
        "--validate",
        help="Compare CSV vs spatial results and report mismatches",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing county associations",
    ),
) -> None:
    """Link districts to counties for QGIS filtering.

    This command associates district boundaries with county names to enable
    filtering in QGIS. It supports two modes:

    1. CSV mode: Use authoritative county-to-district mappings from CSV
       (Georgia only: congressional, state_senate, state_house)

    2. Spatial mode: Use PostGIS spatial joins to automatically determine
       which counties intersect which districts (works for any state/district type)

    3. Validate mode: Compare CSV vs spatial results to identify mismatches

    Examples:

        # Link Georgia districts using CSV (authoritative)
        vote-match link-districts-to-counties data/counties-by-districts-2023.csv

        # Use spatial joins for all districts
        vote-match link-districts-to-counties --spatial

        # Use spatial joins for specific district type
        vote-match link-districts-to-counties --spatial --district-type congressional

        # Validate CSV vs spatial results
        vote-match link-districts-to-counties --validate data/counties-by-districts-2023.csv

        # Filter spatial joins to Georgia counties only
        vote-match link-districts-to-counties --spatial --state-fips 13
    """
    from .county_linking import (
        link_districts_from_csv,
        link_districts_spatial,
        validate_county_links,
    )

    logger.info(
        f"link-districts-to-counties called with csv_file={csv_file}, "
        f"spatial={spatial}, validate={validate}, district_type={district_type}"
    )

    # Validate arguments
    if validate and not csv_file:
        typer.secho(
            "✗ Error: --validate requires a CSV file argument",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    if not csv_file and not spatial:
        typer.secho(
            "✗ Error: Must provide either a CSV file or use --spatial flag",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    # Setup database
    settings = get_settings()
    engine = get_engine(settings)
    session = get_session(engine)

    try:
        # Validation mode
        if validate:
            typer.secho(
                "⚙ Validating county links (CSV vs spatial)...",
                fg=typer.colors.CYAN,
            )
            results = validate_county_links(session, csv_file, district_type)

            typer.secho("\n📊 Validation Results:", fg=typer.colors.YELLOW, bold=True)
            typer.secho(f"  ✓ Matches: {results['matches']}", fg=typer.colors.GREEN)
            typer.secho(f"  ✗ Mismatches: {results['mismatches']}", fg=typer.colors.RED)
            typer.secho(f"  📄 CSV only: {results['csv_only']}", fg=typer.colors.BLUE)
            typer.secho(
                f"  🗺  Spatial only: {results['spatial_only']}",
                fg=typer.colors.MAGENTA,
            )

            # Show mismatch details
            if results["details"]:
                typer.secho("\n⚠ Mismatch Details:", fg=typer.colors.YELLOW, bold=True)
                for detail in results["details"][:10]:  # Limit to 10
                    typer.secho(
                        f"  {detail['district_type']} {detail['district_id']}:",
                        fg=typer.colors.WHITE,
                    )
                    typer.secho(
                        f"    CSV: {', '.join(detail['csv_counties'])}",
                        fg=typer.colors.BLUE,
                    )
                    typer.secho(
                        f"    Spatial: {', '.join(detail['spatial_counties'])}",
                        fg=typer.colors.MAGENTA,
                    )
                if len(results["details"]) > 10:
                    typer.secho(
                        f"  ... and {len(results['details']) - 10} more mismatches",
                        fg=typer.colors.YELLOW,
                    )

        # CSV mode
        elif csv_file:
            typer.secho(
                f"⚙ Linking districts to counties from CSV: {csv_file}",
                fg=typer.colors.CYAN,
            )
            stats = link_districts_from_csv(session, csv_file, overwrite=overwrite)

            typer.secho("\n✓ CSV linking completed!", fg=typer.colors.GREEN, bold=True)
            typer.secho(f"  Updated: {stats['updated']}", fg=typer.colors.GREEN)
            typer.secho(f"  Skipped: {stats['skipped']}", fg=typer.colors.YELLOW)
            typer.secho(f"  Not found: {stats['not_found']}", fg=typer.colors.RED)
            typer.secho(f"  Errors: {stats['errors']}", fg=typer.colors.RED)

        # Spatial mode
        elif spatial:
            typer.secho(
                "⚙ Linking districts to counties using spatial joins...",
                fg=typer.colors.CYAN,
            )
            stats = link_districts_spatial(
                session,
                district_type=district_type,
                state_fips=state_fips,
                overwrite=overwrite,
            )

            typer.secho("\n✓ Spatial linking completed!", fg=typer.colors.GREEN, bold=True)
            typer.secho(f"  Updated: {stats['updated']}", fg=typer.colors.GREEN)
            typer.secho(f"  Skipped: {stats['skipped']}", fg=typer.colors.YELLOW)
            typer.secho(f"  No overlap: {stats['no_overlap']}", fg=typer.colors.BLUE)
            typer.secho(f"  Errors: {stats['errors']}", fg=typer.colors.RED)

        # Next steps
        typer.secho(
            "\n💡 Next steps:",
            fg=typer.colors.YELLOW,
            bold=True,
        )
        typer.secho(
            "  1. Open QGIS and connect to your PostGIS database",
            fg=typer.colors.WHITE,
        )
        typer.secho("  2. Load the district_boundaries layer", fg=typer.colors.WHITE)
        typer.secho(
            "  3. Filter by: district_type = 'congressional' AND county_name LIKE '%BIBB%'",
            fg=typer.colors.WHITE,
        )

    except Exception as e:
        session.close()
        engine.dispose()
        logger.exception("link-districts-to-counties failed with error: {}", e)
        typer.secho(f"✗ Error: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=1)

    finally:
        session.close()
        engine.dispose()


@app.command()
def compare_districts(
    district_type: list[str] | None = typer.Option(
        None,
        "--district-type",
        "-t",
        help=(
            "District type(s) to compare (can be repeated). "
            "Omit to compare ALL types that have imported boundaries."
        ),
    ),
    save_to_db: bool = typer.Option(
        False,
        "--save-to-db",
        help="Persist comparison results to voter_district_assignments table",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        help="Limit number of voters to process (for testing)",
    ),
    legacy: bool = typer.Option(
        False,
        "--legacy",
        help="Run legacy county-commission comparison (backward compat)",
    ),
    export: Path | None = typer.Option(
        None,
        "--export",
        help="(Legacy only) Export mismatches to CSV file",
    ),
) -> None:
    """Compare voter registration districts with spatial district boundaries.

    By default, compares all district types that have boundaries in the
    database. Use --district-type to compare specific types only.

    Uses PostGIS spatial joins to determine which district boundary contains
    each voter's geocoded point, then compares with their voter-roll value.

    Note: Voters must have geocoded locations (run 'geocode' and 'sync-geocode'
    first) and boundaries must be imported (run 'import-geojson' first).
    """
    logger.info("compare-districts command called")

    settings = get_settings()

    try:
        engine = get_engine(settings)
        session = get_session(engine)

        try:
            # --- Legacy path (unchanged behavior) ---
            if legacy:
                district_count = session.query(CountyCommissionDistrict).count()
                if district_count == 0:
                    typer.secho(
                        "✗ No legacy districts found. Run 'import-geojson --legacy' first.",
                        fg=typer.colors.RED,
                        bold=True,
                    )
                    raise typer.Exit(code=1)

                typer.echo(f"Found {district_count} legacy districts in database")

                voters_with_geom = session.query(Voter).filter(Voter.geom.isnot(None)).count()
                if voters_with_geom == 0:
                    typer.secho(
                        "✗ No voters with geocoded locations.",
                        fg=typer.colors.RED,
                        bold=True,
                    )
                    raise typer.Exit(code=1)

                typer.echo(f"Found {voters_with_geom} voters with geocoded locations")

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    transient=False,
                ) as progress:
                    task = progress.add_task("Comparing districts (legacy)...", total=None)
                    from vote_match.processing import (
                        compare_voter_districts,
                        export_district_comparison,
                        update_voter_district_comparison,
                    )

                    result = compare_voter_districts(session=session, limit=limit)
                    progress.update(task, completed=True)

                stats = result["stats"]
                mismatches = result["mismatches"]

                table = Table(
                    title="Legacy District Comparison Results",
                    header_style="bold magenta",
                )
                table.add_column("Metric", style="cyan")
                table.add_column("Count", style="green", justify="right")
                table.add_column("Percentage", style="yellow", justify="right")

                total = stats["total"]
                matched = stats["matched"]
                mismatched = stats["mismatched"]
                no_district = stats["no_district"]

                matched_pct = (matched / total * 100) if total > 0 else 0
                mismatched_pct = (mismatched / total * 100) if total > 0 else 0
                no_district_pct = (no_district / total * 100) if total > 0 else 0

                table.add_row("Total Voters Processed", str(total), "100.0%")
                table.add_row("Matched Districts", str(matched), f"{matched_pct:.1f}%")
                table.add_row("Mismatched Districts", str(mismatched), f"{mismatched_pct:.1f}%")
                table.add_row("No District Found", str(no_district), f"{no_district_pct:.1f}%")

                console.print()
                console.print(table)
                console.print()

                if export:
                    export_district_comparison(mismatches, export)
                    typer.secho(
                        f"✓ Exported {len(mismatches)} mismatches to {export}",
                        fg=typer.colors.GREEN,
                        bold=True,
                    )

                if save_to_db:
                    typer.echo()
                    typer.echo("Updating voters table (legacy columns)...")
                    update_stats = update_voter_district_comparison(
                        session=session,
                        clear_existing=True,
                        limit=limit,
                    )
                    typer.secho(
                        f"✓ Updated {update_stats['records_updated']} voter records "
                        f"({update_stats['mismatched']} mismatches found)",
                        fg=typer.colors.GREEN,
                        bold=True,
                    )
                    typer.echo("Filter in QGIS with: WHERE district_mismatch = true")

                if mismatched > 0:
                    typer.secho(
                        f"Found {mismatched} voters in different districts than registered",
                        fg=typer.colors.YELLOW,
                        bold=True,
                    )
                else:
                    typer.secho(
                        "✓ All voters are in their registered districts",
                        fg=typer.colors.GREEN,
                        bold=True,
                    )
                logger.info("compare-districts (legacy) completed")
                return

            # --- New multi-district path ---
            voters_with_geom = session.query(Voter).filter(Voter.geom.isnot(None)).count()
            if voters_with_geom == 0:
                typer.secho(
                    "✗ No voters with geocoded locations. Run 'geocode' and 'sync-geocode' first.",
                    fg=typer.colors.RED,
                    bold=True,
                )
                raise typer.Exit(code=1)

            typer.echo(f"Found {voters_with_geom} voters with geocoded locations")

            # Check for available boundaries
            boundary_count = session.query(DistrictBoundary).count()
            if boundary_count == 0:
                typer.secho(
                    "✗ No district boundaries found. "
                    "Run 'import-geojson --district-type <type>' first.",
                    fg=typer.colors.RED,
                    bold=True,
                )
                raise typer.Exit(code=1)

            typer.echo(f"Found {boundary_count} district boundaries in database")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=False,
            ) as progress:
                task = progress.add_task("Comparing districts...", total=None)

                from vote_match.processing import compare_all_districts

                results = compare_all_districts(
                    session=session,
                    district_types=district_type,
                    limit=limit,
                    save_to_db=save_to_db,
                )

                progress.update(task, completed=True)

            if not results:
                typer.secho(
                    "No matching district types found for comparison.",
                    fg=typer.colors.YELLOW,
                )
                return

            # Display results per district type
            for dtype, stats in results.items():
                total = stats["total"]
                matched = stats["matched"]
                mismatched = stats["mismatched"]
                no_dist = stats["no_district"]
                no_reg = stats["no_registered"]

                table = Table(
                    title=f"Comparison: {dtype}",
                    header_style="bold magenta",
                )
                table.add_column("Metric", style="cyan")
                table.add_column("Count", style="green", justify="right")
                table.add_column("Percentage", style="yellow", justify="right")

                matched_pct = (matched / total * 100) if total > 0 else 0
                mismatched_pct = (mismatched / total * 100) if total > 0 else 0
                no_dist_pct = (no_dist / total * 100) if total > 0 else 0
                no_reg_pct = (no_reg / total * 100) if total > 0 else 0

                table.add_row("Total Voters", str(total), "100.0%")
                table.add_row("Matched", str(matched), f"{matched_pct:.1f}%")
                table.add_row("Mismatched", str(mismatched), f"{mismatched_pct:.1f}%")
                table.add_row("No Boundary Found", str(no_dist), f"{no_dist_pct:.1f}%")
                table.add_row("No Registration Value", str(no_reg), f"{no_reg_pct:.1f}%")

                console.print()
                console.print(table)

            console.print()

            # Summary across all types
            total_mismatches = sum(s["mismatched"] for s in results.values())
            if total_mismatches > 0:
                typer.secho(
                    f"Found {total_mismatches} total mismatches across "
                    f"{len(results)} district type(s)",
                    fg=typer.colors.YELLOW,
                    bold=True,
                )
            else:
                typer.secho(
                    f"✓ All voters are in their registered districts across {len(results)} type(s)",
                    fg=typer.colors.GREEN,
                    bold=True,
                )

            # Confirm legacy field sync if results were saved
            if save_to_db:
                typer.secho(
                    "✓ Updated legacy district_mismatch field for backward compatibility",
                    fg=typer.colors.GREEN,
                )

            if save_to_db:
                typer.secho(
                    "✓ Results saved to voter_district_assignments table",
                    fg=typer.colors.GREEN,
                    bold=True,
                )

            logger.info("compare-districts completed successfully")

        finally:
            session.close()
            engine.dispose()

    except Exception as e:
        typer.secho(f"✗ Comparison failed: {e}", fg=typer.colors.RED, bold=True)
        logger.exception("compare-districts failed with error: {}", e)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
