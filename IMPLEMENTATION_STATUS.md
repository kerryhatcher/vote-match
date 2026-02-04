# Vote Match CLI - Implementation Status

**Last Updated:** 2026-02-03
**Current Phase:** Phase 3 Complete, Ready for Phase 4

---

## Project Overview

Vote Match is a Python CLI tool for processing Georgia voter registration records for GIS applications. The workflow:
1. Load voter records from CSV into PostGIS database
2. Geocode voter addresses using US Census Batch Geocoder API
3. Match voter records to precincts using spatial joins
4. Generate reports on geocoding and matching success rates

**Technology Stack:**
- Python 3.13+ with `uv` package manager
- Typer CLI framework with Rich output
- SQLAlchemy 2.0 + GeoAlchemy2 for ORM
- PostGIS 17-3.5 for spatial data
- Pandas for CSV processing
- Loguru for logging
- Pytest for testing

---

## ✅ COMPLETED PHASES

### Phase 1: Foundation ✓ COMPLETE

**Status:** Fully implemented and tested

**What was built:**
- Project structure with `src/vote_match/` layout
- All dependencies added via `uv add` (9 runtime, 3 dev)
- `pyproject.toml` configured with:
  - Build system (hatchling)
  - CLI entry point: `vote-match` command
  - Ruff linting/formatting config (line-length=100)
  - Pytest configuration
- Configuration system (`config.py`):
  - Pydantic-settings with `VOTE_MATCH_` env prefix
  - Loads from `.env` file
  - Settings: database_url, log_level, log_file, census config, etc.
- Logging system (`logging.py`):
  - Loguru-based with console and file output
  - Automatic log directory creation
  - Log rotation (10MB) and retention (30 days)
- CLI scaffold (`cli.py`):
  - Typer app with Rich formatting
  - `--verbose` global flag for DEBUG logging
  - All 5 commands stubbed: init-db, load-csv, geocode, status, export
- Test fixtures (`tests/conftest.py`) for database and config
- Docker Compose config for PostGIS (port 35432)
- `.env.example` template

**Files Created:**
- `src/vote_match/__init__.py`
- `src/vote_match/config.py`
- `src/vote_match/logging.py`
- `src/vote_match/cli.py`
- `tests/__init__.py`
- `tests/conftest.py`
- `docker-compose.yml`
- `.env.example`

**Verification:**
- ✅ `uv run vote-match --help` works
- ✅ All dependencies installed
- ✅ Ruff linting passes
- ✅ Logging to console and file works

---

### Phase 2: Database Layer ✓ COMPLETE

**Status:** Fully implemented and tested with actual Georgia voter file structure

**What was built:**
- SQLAlchemy models (`models.py`):
  - `Voter` model with **53 columns** matching actual Georgia voter CSV structure
  - Primary key: `voter_registration_number`
  - All CSV fields as String type (preserves leading zeros)
  - 11 geocoding result fields (status, match_type, coordinates, TIGER/Line IDs, FIPS codes)
  - PostGIS geometry column: `geom` (POINT, SRID 4326)
  - 3 indexes: geocode_status, county, county_precinct
  - `build_street_address()` method for constructing full addresses
- Database module (`database.py`):
  - `get_engine(settings)` - creates SQLAlchemy engine
  - `get_session(engine)` - returns new session
  - `init_database(drop_tables, settings)` - creates PostGIS extension and tables
- CLI `init-db` command fully wired:
  - `--drop` flag with user confirmation
  - Creates PostGIS extension
  - Creates all tables with proper types and indexes
  - Comprehensive error handling
- Docker Compose PostGIS container:
  - Image: `postgis/postgis:17-3.5`
  - Port: 35432 (avoids conflict with system PostgreSQL)
  - Credentials: vote_match / vote_match_dev / vote_match
  - Health checks and persistent volume

**Files Created:**
- `src/vote_match/models.py` (189 lines)
- `src/vote_match/database.py` (77 lines)
- `docker-compose.yml` (updated)

**Files Updated:**
- `src/vote_match/cli.py` (added init-db implementation)
- `.env.example` (updated to port 35432)

**Georgia Voter File Structure (53 columns mapped):**
Core Identity: voter_registration_number, status, status_reason, last_name, first_name, middle_name, suffix, birth_year, race, gender
Residence Address: residence_street_number, residence_pre_direction, residence_street_name, residence_street_type, residence_post_direction, residence_apt_unit_number, residence_city, residence_zipcode
Precincts: county_precinct, county_precinct_description, municipal_precinct, municipal_precinct_description
Districts (14 types): congressional, state_senate, state_house, judicial, county_commission, school_board, city_council, municipal_school_board, water_board, super_council, super_commissioner, super_school_board, fire_district
Other: municipality, combo, land_lot, land_district
Dates: registration_date, last_modified_date, date_of_last_contact, last_vote_date, voter_created_date
Voting History: last_party_voted
Mailing: mailing_street_number, mailing_street_name, mailing_apt_unit_number, mailing_city, mailing_zipcode, mailing_state, mailing_country
County: county

**Verification:**
- ✅ `docker compose up -d` starts PostGIS
- ✅ `uv run vote-match init-db` creates schema
- ✅ PostGIS extension enabled
- ✅ All tables and indexes created
- ✅ Ruff linting passes

---

### Phase 3: CSV Loading ✓ COMPLETE

**Status:** Fully implemented, tested, and verified with actual Georgia data (79 records loaded successfully)

**What was built:**
- CSV reader module (`csv_reader.py`):
  - `COLUMN_MAP`: Maps all 53 Georgia CSV columns to snake_case model attributes
  - `REQUIRED_COLUMNS`: Validates presence of 5 critical columns
  - `read_voter_csv(file_path)`: Reads CSV with dtype=str to preserve leading zeros
  - `dataframe_to_dicts(df)`: Converts DataFrame to dicts with proper NaN→None handling
- CLI `load-csv` command fully wired:
  - Takes `csv_file` path as positional argument
  - `--truncate` flag to clear table before loading
  - PostgreSQL upsert via `INSERT ... ON CONFLICT DO UPDATE`
  - Batch processing (1000 records per batch)
  - Rich progress bar
  - Comprehensive error handling and user feedback
- Test suite (`tests/test_csv_reader.py`):
  - 10 tests covering all functionality
  - File not found, required columns validation
  - Leading zero preservation
  - Column mapping correctness
  - NaN to None conversion
  - 100% code coverage for csv_reader.py

**Files Created:**
- `src/vote_match/csv_reader.py` (144 lines)
- `tests/test_csv_reader.py` (246 lines)

**Files Updated:**
- `src/vote_match/cli.py` (added load-csv implementation)

**Verification:**
- ✅ `uv run pytest` - all 10 tests pass
- ✅ `uv run vote-match load-csv sample.csv` - 79 records loaded successfully
- ✅ Upsert logic works (duplicate registration numbers updated)
- ✅ Leading zeros preserved in zip codes and districts
- ✅ Ruff linting passes

---

## 🔄 IN PROGRESS / NOT STARTED

### Phase 4: Geocoding ❌ NOT STARTED

**What needs to be built:**

#### 1. Geocoder Module (`src/vote_match/geocoder.py`)
**Purpose:** Client for US Census Batch Geocoder API

**Required Components:**
```python
@dataclass
class GeocodeResult:
    """Result from Census geocoder"""
    registration_number: str  # Matches back to voter
    status: str  # 'matched', 'no_match', or 'failed'
    match_type: str | None
    matched_address: str | None
    longitude: float | None
    latitude: float | None
    tigerline_id: str | None
    tigerline_side: str | None
    state_fips: str | None
    county_fips: str | None
    tract: str | None
    block: str | None
```

**Functions to Implement:**
- `build_batch_csv(voters: list[Voter]) -> str`
  - Format: `{id},{street},{city},{state},{zip}` (no header)
  - Use `voter.build_street_address()` for street
  - Use `voter.residence_city` for city
  - State: hardcoded "GA" (or from settings)
  - Use `voter.residence_zipcode` for zip

- `submit_batch(csv_content: str, settings: Settings) -> str`
  - POST to `https://geocoding.geo.census.gov/geocoder/geographies/addressbatch`
  - Form data: `addressFile` (multipart upload), `benchmark`, `vintage`
  - Timeout: 300 seconds (configurable)
  - Max batch: 10,000 records
  - Returns: Response CSV text

- `parse_response(response_text: str) -> list[GeocodeResult]`
  - Parse Census response CSV
  - Response format: `id,input_address,match_indicator,match_type,matched_address,lon/lat,TIGER/Line_ID,Side,State_FIPS,County_FIPS,Tract,Block`
  - Handle "Match", "No_Match", "Tie" statuses
  - Map to GeocodeResult objects

**Dependencies:**
- `httpx` for HTTP client (already installed)
- `dataclasses` for GeocodeResult
- Settings for benchmark/vintage/timeout config

**Tests to Create:**
- Mock HTTP responses
- Test CSV formatting
- Test response parsing
- Test error handling

---

#### 2. Processing Module (`src/vote_match/processing.py`)
**Purpose:** Orchestrate resumable geocoding workflow

**Resumable Strategy:**
1. Records inserted by `load-csv` have `geocode_status = NULL`
2. Query for records with `geocode_status IS NULL`
3. Process in batches (up to 10,000 per API call)
4. On success: set `geocode_status = 'matched'` or `'no_match'`, populate geocode fields and geom
5. On failure: set `geocode_status = 'failed'`
6. Each batch committed independently (crash-safe)
7. `--retry-failed` flag re-processes records with status `'failed'`
8. `--limit` controls total records to process per run

**Functions to Implement:**
- `get_pending_voters(session, limit: int | None, retry_failed: bool) -> list[Voter]`
  - Query for `geocode_status IS NULL` (or `= 'failed'` if retry_failed)
  - Order by voter_registration_number
  - Limit to `limit` records if specified

- `apply_geocode_results(session, results: list[GeocodeResult]) -> int`
  - Update voter records with geocoding results
  - Set all geocode_* fields
  - Construct WKT POINT from lon/lat and set `geom` column using `ST_GeomFromText`
  - Return count of updated records

- `process_geocoding(session, settings, batch_size, limit, retry_failed) -> dict`
  - Main orchestration function
  - Loop: get pending voters → geocode batch → apply results → commit
  - Return stats: total_processed, matched, no_match, failed

**Spatial Data Handling:**
```python
from geoalchemy2 import WKTElement
# Create geometry from lon/lat
if result.longitude and result.latitude:
    wkt = f"POINT({result.longitude} {result.latitude})"
    voter.geom = WKTElement(wkt, srid=4326)
```

**Tests to Create:**
- Test get_pending_voters query logic
- Test apply_geocode_results updates
- Test process_geocoding orchestration
- Test resumability (partial batch failure)

---

#### 3. CLI `geocode` Command (`src/vote_match/cli.py`)
**Purpose:** User-facing command for geocoding

**Command Signature:**
```python
@app.command()
def geocode(
    batch_size: int = typer.Option(default_batch_size, help="Records per API call (max 10000)"),
    limit: int | None = typer.Option(None, help="Total records to process"),
    retry_failed: bool = typer.Option(False, help="Retry previously failed records"),
):
    """Geocode voter addresses using US Census Batch Geocoder."""
```

**Implementation:**
- Call `processing.process_geocoding()`
- Display progress with Rich progress bar
- Show summary table: total processed, matched, no_match, failed
- Handle API errors gracefully
- Log to file for debugging

**User Feedback:**
```
Geocoding voter addresses...
  Processing batch 1/3... ━━━━━━━━━━━━━━━━━━━━━━━━━━ 10000/10000
  Processing batch 2/3... ━━━━━━━━━━━━━━━━━━━━━━━━━━ 10000/10000
  Processing batch 3/3... ━━━━━━━━━━━━━━━━━━━━━━━━━━ 5432/5432

✓ Geocoding complete
  ┌─────────────┬────────┐
  │ Status      │ Count  │
  ├─────────────┼────────┤
  │ Matched     │ 24,892 │
  │ No Match    │    320 │
  │ Failed      │    220 │
  │ Total       │ 25,432 │
  └─────────────┴────────┘
```

---

### Phase 5: Reporting ❌ NOT STARTED

**What needs to be built:**

#### 1. CLI `status` Command (`src/vote_match/cli.py`)
**Purpose:** Show geocoding statistics

**Implementation:**
```python
@app.command()
def status():
    """Display voter record and geocoding statistics."""
    # Query aggregate counts:
    # - Total records
    # - Pending (geocode_status IS NULL)
    # - Matched (geocode_status = 'matched')
    # - No Match (geocode_status = 'no_match')
    # - Failed (geocode_status = 'failed')

    # Group by county for breakdown

    # Display Rich table with results
```

**Output Example:**
```
Voter Record Status

Overall Statistics:
  ┌──────────────┬────────┬─────────┐
  │ Status       │ Count  │ Percent │
  ├──────────────┼────────┼─────────┤
  │ Total        │ 25,432 │  100.0% │
  │ Pending      │      0 │    0.0% │
  │ Matched      │ 24,892 │   97.9% │
  │ No Match     │    320 │    1.3% │
  │ Failed       │    220 │    0.9% │
  └──────────────┴────────┴─────────┘

By County:
  ┌─────────────┬────────┬─────────┬──────────┐
  │ County      │ Total  │ Matched │ Match %  │
  ├─────────────┼────────┼─────────┼──────────┤
  │ FULTON      │ 12,456 │  12,321 │   98.9% │
  │ COBB        │  8,932 │   8,742 │   97.9% │
  │ DEKALB      │  4,044 │   3,829 │   94.7% │
  └─────────────┴────────┴─────────┴──────────┘
```

---

#### 2. CLI `export` Command (`src/vote_match/cli.py`)
**Purpose:** Export records to CSV or GeoJSON

**Command Signature:**
```python
@app.command()
def export(
    output: Path = typer.Argument(..., help="Output file path"),
    format: str = typer.Option("csv", help="Output format: csv or geojson"),
    matched_only: bool = typer.Option(False, help="Export only geocoded records"),
):
    """Export voter records to CSV or GeoJSON."""
```

**Implementation:**
- Query voters (with optional filter: `geocode_status = 'matched'`)
- For CSV: Convert to DataFrame and write with pandas
- For GeoJSON: Construct FeatureCollection with geometry from `geom` column
  ```python
  {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {voter_fields...}
      }
    ]
  }
  ```
- Show progress bar for large exports
- Report records exported

**CSV Export:** All columns, suitable for sharing or analysis
**GeoJSON Export:** For use in GIS applications (QGIS, ArcGIS, web maps)

---

## Development Workflow

### Running Commands
```bash
# Start database
docker compose up -d

# Initialize schema (first time or after model changes)
uv run vote-match init-db

# Load voter CSV
uv run vote-match load-csv path/to/voters.csv

# Geocode addresses (all pending)
uv run vote-match geocode

# Geocode in smaller batches
uv run vote-match geocode --limit 1000 --batch-size 500

# Retry failed records
uv run vote-match geocode --retry-failed

# Check status
uv run vote-match status

# Export results
uv run vote-match export output.csv --matched-only
uv run vote-match export output.geojson --format geojson
```

### Code Quality
```bash
# Lint
uv run ruff check src/ tests/

# Format
uv run ruff format src/ tests/

# Test
uv run pytest
uv run pytest --cov=vote_match --cov-report=html

# Type check (if we add mypy later)
uv run mypy src/
```

### Database Management
```bash
# Rebuild schema
uv run vote-match init-db --drop

# Connect to database
docker exec -it vote-match-db psql -U vote_match -d vote_match

# View tables
\dt

# Check PostGIS
SELECT PostGIS_version();

# Sample queries
SELECT COUNT(*) FROM voters;
SELECT geocode_status, COUNT(*) FROM voters GROUP BY geocode_status;
SELECT * FROM voters WHERE geocode_status = 'matched' LIMIT 5;
```

---

## Configuration

### Environment Variables (`.env`)
```bash
VOTE_MATCH_DATABASE_URL=postgresql+psycopg://vote_match:vote_match_dev@localhost:35432/vote_match
VOTE_MATCH_LOG_LEVEL=INFO
VOTE_MATCH_LOG_FILE=logs/vote-match.log
VOTE_MATCH_DEFAULT_STATE=GA
VOTE_MATCH_DEFAULT_BATCH_SIZE=10000
VOTE_MATCH_CENSUS_TIMEOUT=300
```

### Census Geocoder Settings
- **Endpoint:** `https://geocoding.geo.census.gov/geocoder/geographies/addressbatch`
- **Benchmark:** `Public_AR_Current` (most recent)
- **Vintage:** `Current_Current` (most recent geography)
- **Max Batch:** 10,000 records per request
- **Rate Limits:** Not documented, but be respectful
- **Documentation:** https://geocoding.geo.census.gov/geocoder/

---

## Known Issues / Gotchas

1. **Port Conflict:** System PostgreSQL on 5432 conflicts with Docker. Solution: Use port 35432
2. **Leading Zeros:** Must use `dtype=str` when reading CSV to preserve zip/district codes
3. **NaN Handling:** Pandas NaN must be converted to Python None for SQLAlchemy
4. **Geometry Column:** Must use `ST_GeomFromText()` or `WKTElement` to set PostGIS geometry
5. **Census API:** Can be slow for large batches (300s timeout may not be enough for 10k records)
6. **Column Names:** Georgia CSV has specific column names - don't assume generic structure

---

## Testing Strategy

### Unit Tests
- ✅ CSV reader (Phase 3)
- ❌ Geocoder module (Phase 4)
- ❌ Processing module (Phase 4)

### Integration Tests
- ❌ Full workflow: load → geocode → export
- ❌ Database operations with PostGIS
- ❌ API mocking for geocoder

### Manual Testing
- ✅ CLI help messages
- ✅ Database initialization
- ✅ CSV loading with actual data
- ❌ Geocoding with Census API
- ❌ Export to CSV/GeoJSON

---

## Next Steps (Priority Order)

1. **Implement Phase 4: Geocoding**
   - Start with `geocoder.py` module
   - Then `processing.py` orchestration
   - Wire CLI `geocode` command
   - Add tests with mocked API responses
   - Test with small batch (10-20 records) of real data

2. **Implement Phase 5: Reporting**
   - Wire `status` command (quick win)
   - Wire `export` command for CSV
   - Add GeoJSON export support

3. **Documentation & Polish**
   - Add README usage examples
   - Document Census API quirks
   - Add troubleshooting guide
   - Consider adding `--dry-run` flags

4. **Optional Enhancements**
   - Add precinct matching (spatial join)
   - Add data quality reports
   - Add configuration file support
   - Add database backup/restore commands
   - Consider async processing for large batches

---

## File Inventory

### Source Code (src/vote_match/)
- ✅ `__init__.py` - Package initialization
- ✅ `cli.py` - Typer CLI app (189 lines, 3/5 commands implemented)
- ✅ `config.py` - Pydantic settings (41 lines)
- ✅ `logging.py` - Loguru configuration (44 lines)
- ✅ `models.py` - SQLAlchemy models (189 lines, 53 CSV columns + geocoding fields)
- ✅ `database.py` - Database operations (77 lines)
- ✅ `csv_reader.py` - CSV loading (144 lines)
- ❌ `geocoder.py` - Census API client (NOT CREATED)
- ❌ `processing.py` - Geocoding orchestration (NOT CREATED)

### Tests (tests/)
- ✅ `__init__.py` - Test package
- ✅ `conftest.py` - Pytest fixtures (31 lines)
- ✅ `test_csv_reader.py` - CSV tests (246 lines, 10 tests, 100% coverage)
- ❌ `test_geocoder.py` - Geocoder tests (NOT CREATED)
- ❌ `test_processing.py` - Processing tests (NOT CREATED)

### Configuration
- ✅ `pyproject.toml` - Dependencies, build config, tool config
- ✅ `.env.example` - Environment variable template
- ✅ `docker-compose.yml` - PostGIS container
- ✅ `.gitignore` - Includes .env, logs/, __pycache__, etc.

### Documentation
- ✅ `README.md` - Project overview
- ✅ `CLAUDE.md` - Developer guidance for Claude Code
- ✅ `IMPLEMENTATION_STATUS.md` - This file

### Data
- ✅ `sample.csv` - 79 Georgia voter records (gitignored)

---

## Key Decisions & Rationale

### Why Batch Geocoding?
- Census API designed for batch processing (up to 10k records)
- More efficient than individual requests
- Handles rate limiting better
- Can process overnight for large datasets

### Why PostGIS?
- Native spatial types and functions
- Industry standard for GIS data
- Enables future spatial queries (precinct matching)
- Better performance than storing lat/lon as separate columns

### Why String Types for CSV?
- Preserves leading zeros in zip codes (30303 not 30303)
- Preserves leading zeros in district codes (01 not 1)
- Matches state data format exactly
- Avoids type coercion issues

### Why Resumable Processing?
- Large datasets take hours to geocode
- API can fail mid-batch
- Allows incremental progress
- Supports re-running only failures

### Why SQLAlchemy Upsert?
- Handles duplicate registration numbers gracefully
- Allows re-loading CSV with updates
- Idempotent operations (safe to re-run)
- PostgreSQL-specific but efficient

---

## Dependencies Rationale

| Package | Purpose | Why This One? |
|---------|---------|---------------|
| typer | CLI framework | Best Python CLI library, Rich integration, type-safe |
| loguru | Logging | Simpler than stdlib logging, great defaults |
| pandas | CSV processing | Industry standard, handles CSV quirks well |
| sqlalchemy | ORM | Most mature Python ORM, great PostgreSQL support |
| geoalchemy2 | PostGIS types | Official SQLAlchemy extension for PostGIS |
| psycopg | PostgreSQL driver | Psycopg3 is modern, fast, and well-maintained |
| pydantic-settings | Config | Type-safe, env var support, 12-factor app pattern |
| httpx | HTTP client | Modern, async-capable (for future), clean API |
| shapely | Geometry ops | Industry standard, used by geoalchemy2 |
| ruff | Linting/formatting | Fastest linter, replaces flake8+black+isort |
| pytest | Testing | Industry standard, great ecosystem |
| pytest-cov | Coverage | Best coverage integration for pytest |

---

## Contact & Support

For issues or questions:
- Check logs in `logs/vote-match.log`
- Run with `--verbose` flag for debug output
- Review this document for known issues
- Check Census API documentation: https://geocoding.geo.census.gov/geocoder/

---

**End of Implementation Status Document**
