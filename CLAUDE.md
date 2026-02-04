# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

### Workflow

1. **Geocode with services**: Results are saved to GeocodeResult table
   - `vote-match geocode --service census` - Primary service
   - `vote-match geocode --service nominatim` - Alternative for no_match records

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
