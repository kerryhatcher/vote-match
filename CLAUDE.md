# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Vote Match is a Python tool for processing voter registration records for GIS applications. The primary workflow involves:

1. Converting voter records from CSV format to PostGIS records
2. Geocoding voter addresses using various geocoding services
3. Matching voter records to precincts using spatial joins
4. Generating reports on geocoding and matching success rates

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

### Important Notes

- **PostGIS extension is NOT managed by migrations** - it requires superuser privileges and is handled separately in `init_database()`
- **Migration files are stored in** `alembic/versions/`
- **Always review auto-generated migrations** before applying them
- **Test migrations in development** before applying to production
- **Migration commands**: `db-migrate`, `db-upgrade`, `db-downgrade`, `db-current`, `db-history`, `db-stamp`
- **Always lint code with ruff** before committing changes

## Important Notes

- The `sample.csv` file is gitignored and contains voter registration data. Do not commit voter data files to version control.
- PostGIS database integration will be required for the spatial operations (not yet implemented)
