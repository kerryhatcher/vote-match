# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

[Project Background](docs/PROJECT_SUMMARY.md)

## Project Overview

Vote Match is a Python tool for processing voter registration records for GIS applications. The primary workflow involves:

1. Converting voter records from CSV format to PostGIS records
2. Geocoding voter addresses using various geocoding services
3. Syncing best geocoding results to the Voter table for QGIS visualization
4. Matching voter records to precincts using spatial joins
5. Generating reports on geocoding and matching success rates

### Key CLI Commands

- `vote-match init-db` - Initialize PostGIS database schema
- `vote-match load-csv <file>` - Import voter registration CSV
- `vote-match geocode --service <name>` - Geocode addresses using specified service (census, nominatim, etc.)
- `vote-match sync-geocode` - **Required for QGIS**: Sync best geocoding results to Voter table
- `vote-match delete-geocode-results --service <name> --status <status>` - Delete geocoding results for retry
- `vote-match import-shapefiles` - Batch import all district shapefiles from data folder
- `vote-match import-geojson <file> --district-type <type>` - Import individual district shapefile/GeoJSON
- `vote-match compare-districts --district-type <type>` - Compare voter registered districts vs spatial districts
- `vote-match status` - View geocoding statistics and progress
- `vote-match export <file>` - Export voter data to CSV or GeoJSON

## Development Commands

### Running the Application

```bash
uv run main.py
```

### Package Management

```bash
# Add a dependency
uv add <package-name>

# Add a dev dependency
uv add --dev <package-name>

# Remove a package
uv remove <package-name>
```

### Code Quality

```bash
# Lint Python code with ruff
uv run ruff check .

# Format code with ruff
uv run ruff format .
```

Always lint code before committing changes.

## Data Structure

The project works with voter registration CSV files with the following key fields:

- Voter identification: Registration Number, Status, Name fields
- Address components: Street Number, Direction, Street Name, Type, Apt/Unit, City, Zipcode
- Geographic divisions: County Precinct, Congressional District, State Senate/House Districts, Municipality
- Demographics: Birth Year, Race, Gender
- Voting history: Last Vote Date, Last Party Voted

Sample data is available in `sample.csv` for reference.

## Technical Requirements

- Python 3.13+
- Uses `uv` for all Python operations (never use system `python` or `python3`)
- Project managed via `pyproject.toml`

## Geocoding Architecture

Vote Match uses a multi-service geocoding architecture that supports cascading strategies:

### Database Schema

- **GeocodeResult table**: Stores geocoding results from multiple services
  - One voter can have multiple results (one per service)
  - Each result includes: service_name, status, coordinates, confidence, raw_response
  - Status values: exact, interpolated, approximate, no_match, failed

- **Voter table**: Contains voter data and best geocoding result
  - `geom` column: PostGIS POINT geometry (required for QGIS visualization)
  - Legacy `geocode_*` fields: For backward compatibility

### Available Geocoding Services

Vote Match supports multiple geocoding services with different characteristics:

**Free Services:**

- **census** (BATCH): US Census Batch Geocoder - US only, batch processing, no API key required
- **nominatim** (INDIVIDUAL): OpenStreetMap/Nominatim - Global, 1 req/sec rate limit, requires email in config
- **photon** (INDIVIDUAL): Komoot/Photon - Global, free OSM-based service, 1 req/sec recommended

**Paid Services:**

- **geocodio** (BATCH): Geocodio API - US/Canada only, excellent batch support (up to 10,000 addresses), requires API key
- **mapbox** (BATCH): Mapbox Geocoding v6 - Global coverage, batch support (up to 1000 addresses), requires access token
- **google** (INDIVIDUAL): Google Maps Geocoding API - Global, premium quality, expensive, requires API key

### Workflow

1. **Geocode with services**: Results are saved to GeocodeResult table
   - `vote-match geocode --service census` - Primary free service (US only)
   - `vote-match geocode --service geocodio` - Premium batch service (US/Canada)
   - `vote-match geocode --service mapbox` - Premium batch service (global)
   - `vote-match geocode --service nominatim` - Alternative free service for no_match records
   - `vote-match geocode --service photon` - Alternative free service (global)
   - `vote-match geocode --service google` - Premium individual service (expensive)

2. **Sync best results**: Updates Voter table for QGIS
   - `vote-match sync-geocode` - Selects best result and updates `geom` column
   - Best result determined by quality: exact > interpolated > approximate

3. **QGIS visualization**: Connect to PostGIS and display voters layer
   - The `geom` column must be populated via `sync-geocode` command

### Retrying Failed Geocodes

If geocoding fails, you can delete the failed results and retry with the same or different service:

1. **Delete failed results**: Remove previous failed attempts

   ```bash
   vote-match delete-geocode-results --service census --status failed
   ```

2. **Retry geocoding**: Use the cascading strategy to retry

   ```bash
   vote-match geocode --service census --only-unmatched --retry-failed
   ```

3. **Sync to Voter table**: Update geometry for QGIS visualization

   ```bash
   vote-match sync-geocode
   ```

**Common scenarios:**

- Retry same service after transient errors: Delete `failed` status for that service
- Try different service: Delete `no_match` status to allow new service to process
- Reprocess everything: Use `--all` flag (with confirmation)

### Adding New Geocoding Services

New services are registered in `src/vote_match/geocoding/registry.py`:

1. Create service class in `src/vote_match/geocoding/services/`
2. Inherit from `GeocodeService` base class
3. Implement `geocode_batch()` method
4. Register with `@GeocodeServiceRegistry.register()` decorator

## District Management

Vote Match supports importing and comparing district boundaries for spatial analysis.

### Supported District Types

The following district types are supported (see `DISTRICT_TYPES` in `models.py`):

- **county** - County Boundaries (for filtering districts by county)
- **congressional** - US Congressional Districts
- **state_senate** - State Senate Districts
- **state_house** - State House/Assembly Districts
- **county_commission** - County Commission Districts
- **school_board** - School Board Districts
- **county_precinct** - County Voting Precincts
- **psc** - Public Service Commission Districts
- **city_council** - City Council Districts
- **judicial** - Judicial Districts
- **municipality** - City/Town Boundaries
- **fire** - Fire Districts
- **water_board** - Water Board Districts
- Other super-districts and municipal districts

### Batch Import Workflow

For importing multiple district shapefiles at once:

1. **Place shapefiles in data directory**
   - Files must be in ZIP format containing shapefiles
   - Filename prefixes are auto-mapped to district types:
     - `congress-*.zip` → congressional
     - `senate-*.zip` → state_senate
     - `house-*.zip` → state_house
     - `bibbcc-*.zip` → county_commission
     - `bibbsb-*.zip` → school_board
     - `gaprec-*.zip` → county_precinct
     - `psc-*.zip` → psc

2. **Run batch import**

   ```bash
   vote-match import-shapefiles --data-dir data
   ```

3. **Verify import**

   ```bash
   # Check imported districts in database
   psql -d vote_match -c "SELECT district_type, COUNT(*) FROM district_boundaries GROUP BY district_type;"
   ```

**Import options:**

- `--skip-existing` (default: True) - Skip district types that already have boundaries
- `--no-skip-existing` - Re-import even if boundaries exist
- `--clear` - Delete all existing boundaries before importing (requires confirmation)

### Individual Import

For importing a single district file:

```bash
vote-match import-geojson data/congress-2023-shape.zip --district-type congressional
```

Supports: `.geojson`, `.json`, `.shp`, `.zip` (containing shapefiles)

### District Comparison

Compare voter registered districts vs spatial districts using PostGIS spatial joins:

```bash
# Compare single district type
vote-match compare-districts --district-type congressional --save-to-db

# Compare multiple district types
vote-match compare-districts --district-type congressional --district-type state_senate --save-to-db
```

**Note:** When using `--save-to-db`, the legacy `district_mismatch` field is automatically updated for backward compatibility with existing QGIS projects.

### Export with District Type Filtering

Export voters with mismatches for specific district type(s):

```bash
# Export state senate mismatches to CSV
vote-match export bibb-senate-mismatches.csv \
  --county BIBB \
  --mismatch-only \
  --district-type state_senate

# Export to interactive web map with correct district boundaries
vote-match export bibb-senate-map.html \
  --format leaflet \
  --county BIBB \
  --mismatch-only \
  --district-type state_senate \
  --include-districts \
  --redact-pii

# Multiple district types (voters mismatched in EITHER type)
vote-match export mismatches.csv \
  --mismatch-only \
  --district-type state_senate \
  --district-type congressional

# Export all mismatches (any district type)
vote-match export all-mismatches.csv \
  --mismatch-only
```

**Key features:**

- `--district-type` filters by specific district type(s) when using `--mismatch-only`
- Without `--district-type`, uses legacy `district_mismatch` field (any mismatch)
- Leaflet maps show correct district boundaries for the specified type
- Can be combined with `--county` for geographic filtering

### QGIS Filtering by District Type

To filter voters by specific district type mismatches in QGIS:

#### Option 1: Simple (any mismatch)

```sql
"district_mismatch" = true
```

#### Option 2: Specific district type (requires JOIN)

Since `VoterDistrictAssignment` tracks per-district-type mismatches, you can create a QGIS relationship:

1. Add both `voters` and `voter_district_assignments` layers to QGIS
2. Create a relationship: `voters.voter_registration_number` → `voter_district_assignments.voter_id`
3. Filter voters layer:

   ```sql
   "voter_registration_number" IN (
     SELECT voter_id FROM voter_district_assignments
     WHERE district_type = 'state_senate' AND is_mismatch = true
   )
   ```

#### Option 3: Export filtered data

For simpler QGIS workflows, export filtered data directly:

```bash
vote-match export qgis-senate-mismatches.geojson \
  --format geojson \
  --mismatch-only \
  --district-type state_senate \
  --county BIBB
```

### County-Based Filtering

Vote Match supports filtering districts by county in QGIS. This enables spatial analysis and visualization of districts within specific counties.

**Workflow:**

1. **Import county boundaries** (one-time setup):

   ```bash
   vote-match import-geojson data/tl_2025_us_county.zip --district-type county
   ```

   This imports ~3,200 US county boundaries from Census TIGER/Line shapefiles.

2. **Link districts to counties**:

   **Option A: Use CSV mapping (Georgia only, authoritative)**

   ```bash
   vote-match link-districts-to-counties data/counties-by-districts-2023.csv
   ```

   Uses official Georgia state mappings for congressional, state senate, and state house districts.

   **Option B: Use spatial joins (any state, automatic)**

   ```bash
   # Link all district types
   vote-match link-districts-to-counties --spatial

   # Link specific district type
   vote-match link-districts-to-counties --spatial --district-type congressional

   # Filter to Georgia counties only
   vote-match link-districts-to-counties --spatial --state-fips 13
   ```

   Uses PostGIS `ST_Intersects` to automatically determine which counties overlap which districts.

3. **Validate mappings** (optional):

   ```bash
   vote-match link-districts-to-counties --validate data/counties-by-districts-2023.csv
   ```

   Compares CSV mappings vs spatial joins to identify mismatches.

**QGIS Filtering Examples:**

Once districts are linked to counties, you can filter in QGIS using the `county_name` attribute:

```sql
-- Show congressional districts in Bibb County
"district_type" = 'congressional' AND "county_name" LIKE '%BIBB%'

-- Show all districts in multiple counties
"county_name" LIKE '%BIBB%' OR "county_name" LIKE '%MONROE%'

-- Show districts entirely within a single county (not spanning multiple)
"county_name" = 'BIBB'
```

**Notes:**

- Many Georgia districts span multiple counties - their `county_name` contains comma-separated values (e.g., "BIBB, MONROE, JONES")
- County names are normalized to uppercase without "County" suffix
- CSV provides authoritative mappings for Georgia; spatial joins work nationwide
- Use `--overwrite` flag to update existing county associations

### QGIS Visualization

1. Connect to PostGIS database
2. Load `district_boundaries` layer
3. Filter by `district_type` to view specific districts
4. Style polygons by district properties (name, party, etc.)
5. Overlay with `voters` layer (requires `sync-geocode` first)

## Database Migrations

Vote Match uses Alembic for database schema migrations. When making changes to the database schema, follow this workflow:

### Workflow for Schema Changes

1. **Modify models.py**: Make your changes to `src/vote_match/models.py`

2. **Generate migration**: Create a new migration file with a descriptive message

   ```bash
   vote-match db-migrate -m "Add new column to voters table"
   ```

3. **Review migration**: Check the generated file in `alembic/versions/`
   - Alembic auto-generates migrations by comparing models to the database
   - Always review before applying to ensure correctness
   - Edit if necessary (e.g., add data migrations, handle special cases)

4. **Apply migration**: Upgrade the database to the latest schema

   ```bash
   vote-match db-upgrade
   ```

5. **Test**: Verify the changes work correctly with your application

6. **Test rollback**: Ensure the migration can be rolled back

   ```bash
   vote-match db-downgrade <previous-revision>
   ```

7. **Re-apply**: Upgrade back to head

   ```bash
   vote-match db-upgrade
   ```

8. **Lint code**: Always lint before committing

   ```bash
   uv run ruff check .
   uv run ruff format .
   ```

### Migration Notes

- **PostGIS extension is NOT managed by migrations** - it requires superuser privileges and is handled separately in `init_database()`
- **Migration files are stored in** `alembic/versions/`
- **Always review auto-generated migrations** before applying them
- **Test migrations in development** before applying to production
- **Migration commands**: `db-migrate`, `db-upgrade`, `db-downgrade`, `db-current`, `db-history`, `db-stamp`
- **Always lint code with ruff** before committing changes

## Additional Notes

- The `sample.csv` file is gitignored and contains voter registration data. Do not commit voter data files to version control.
- PostGIS database integration will be required for the spatial operations (not yet implemented)
