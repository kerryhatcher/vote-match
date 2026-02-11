# Copilot Code Review Instructions

## Project Overview

Vote Match is a Python CLI tool for processing voter registration records for GIS applications. It loads voter data from CSV, geocodes addresses via multiple services, stores results in PostGIS, and compares voter district assignments against spatial boundaries for all office types (congressional, state senate, state house, county commission, school board, etc.).

## Language & Runtime

- Python 3.13+ only
- Package management via `uv` (never bare `python` or `pip`)
- Project defined in `pyproject.toml` with hatchling build backend
- CLI framework: Typer with Rich for output formatting

## Code Style & Linting

- Linter/formatter: **ruff** with `line-length = 100` and `target-version = "py313"`
- Flag lines exceeding 100 characters
- Prefer `str | None` union syntax over `Optional[str]` (Python 3.13 style)
- All string columns in the Voter model must be `String` (not `Integer`) to preserve leading zeros in voter registration data (zip codes, district IDs, FIPS codes)

## Database & ORM Conventions

- ORM: SQLAlchemy 2.0 declarative style with `declarative_base()`
- Geometry: GeoAlchemy2 for PostGIS columns (SRID 4326 / WGS84)
- Migrations: Alembic in `alembic/versions/`; every schema change must have a migration
- PostGIS extension is NOT managed by Alembic (requires superuser)
- Use PostgreSQL-specific `INSERT ... ON CONFLICT` (upsert) for bulk loads
- Batch operations should commit in chunks (typically 1000 records)

## Key Review Checks

- **No voter PII in commits**: sample.csv, voter data files, and .env must never be committed
- **No hardcoded API keys or credentials**: geocoding service keys come from environment/config
- **SQL injection**: raw SQL via `sqlalchemy.text()` must use bind parameters (`:param`), never f-strings for user-supplied values
- **CRS handling**: any spatial data imported from shapefiles or GeoJSON must be reprojected to EPSG:4326 before storage
- **Migration safety**: review that `upgrade()` and `downgrade()` are inverses; flag destructive column drops without data migration
- **Geocoding service registration**: new services must inherit from `GeocodeService`, implement `geocode_batch()`, and register via `@GeocodeServiceRegistry.register()`

## Architecture Patterns

- `src/vote_match/models.py` - SQLAlchemy models; `DISTRICT_TYPES` maps district type keys to Voter column names
- `src/vote_match/processing.py` - business logic (geocoding, district comparison, map generation)
- `src/vote_match/cli.py` - Typer CLI commands; thin wrappers that call into processing functions
- `src/vote_match/geocoding/services/` - one module per geocoding provider
- `src/vote_match/config.py` - Pydantic settings from environment variables

## Testing

- Framework: pytest with coverage (`pytest-cov`)
- Test directory: `tests/`
- Flag new processing functions that lack corresponding tests

## Common Mistakes to Flag

- Using `Integer` type for columns that can have leading zeros (zip codes, district IDs)
- Forgetting to close database sessions and dispose engines in CLI commands
- Missing `session.commit()` after bulk operations
- Importing `CountyCommissionDistrict` for new code instead of the generic `DistrictBoundary` model
- Hardcoding district type strings instead of referencing `DISTRICT_TYPES` keys
- Omitting `--legacy` backward-compatibility paths when modifying `import-geojson` or `compare-districts`
