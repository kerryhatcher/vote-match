# Vote Match
script to process voter records for use in GIS.


## Functionality

- Convert voter records from CSV to postGIS records
- Geocode voter addresses using a variety of services
- Match voter records to precincts using spatial joins
- Generate reports on geocoding and matching success rates


## Technologies Used

Python is the primary programming language used. 
`UV` should be used to manage Python virtual environment and dependencies. IMPORTANT: DO NOT USE PIP or POETRY.
PostGIS is used for spatial data storage and processing.
GDAL is used for geospatial data manipulation.
The primary interface is a command-line interface (CLI). Use Typer to build and manage the CLI.
Address validating via USPS API. See [USPS API spec](docs/USPS_API_addresses-v3r2_2.yaml) for details.

### Perfered Packages

- pandas
- loguru
- typer


## Database Migrations

Vote Match uses Alembic for database schema migrations. This allows you to track and manage database schema changes over time.

### Fresh Database Setup

For a new database, simply run:

```bash
vote-match init-db
```

This will:

1. Create the PostGIS extension
2. Create all database tables
3. Apply all migrations and set up migration tracking

If you need to start fresh with an existing database:

```bash
vote-match init-db --drop
```

**Warning**: This will delete all existing data and migration history.

### Making Schema Changes

When you need to modify the database schema:

1. **Modify the models** in `src/vote_match/models.py`

2. **Generate a migration** with a descriptive message:

   ```bash
   vote-match db-migrate -m "Add user preferences table"
   ```

3. **Review the generated migration** in `alembic/versions/`
   - Alembic auto-generates the migration based on model changes
   - Always review before applying to ensure correctness

4. **Apply the migration** to update your database:

   ```bash
   vote-match db-upgrade
   ```

5. **Test the changes** to ensure everything works as expected

### Migration Commands

| Command                              | Description                                                                  |
| ------------------------------------ | ---------------------------------------------------------------------------- |
| `vote-match db-migrate -m "message"` | Create a new migration file based on model changes                           |
| `vote-match db-upgrade [revision]`   | Apply migrations (default: latest)                                           |
| `vote-match db-downgrade <revision>` | Rollback to a specific migration revision                                    |
| `vote-match db-current`              | Show the current migration revision                                          |
| `vote-match db-history`              | List all available migrations                                                |
| `vote-match db-stamp <revision>`     | Mark database as being at a specific revision without running migrations     |

### Migrating an Existing Database

If you have an existing database that was created without migrations, you have two options:

#### Option A: Fresh Start (Recommended for Development)

```bash
# Back up your data first!
vote-match export data-backup.csv

# Drop and recreate with migrations
vote-match init-db --drop

# Reload your data
vote-match load-csv data-backup.csv
```

#### Option B: Stamp Existing Database

If you can't recreate the database (e.g., production), stamp it to mark it as current:

```bash
# Stamp the database at the current schema version
vote-match db-stamp head
```

This tells Alembic that your database is already at the latest migration without actually running the migrations.

**Important Notes:**
- The PostGIS extension is NOT managed by migrations (requires superuser privileges)
- Migration files are stored in `alembic/versions/`
- Always review auto-generated migrations before applying them
- Test migrations in development before applying to production

## Developer Conventions
- Follow PEP 8 style guidelines.
- Write clear and concise docstrings for all functions and classes.
- Use type hints for function signatures.
- Write unit tests for all new functionality.
- Use Git for version control and follow a branching strategy (e.g., Git Flow).
- Use conventional commit messages for clarity.
- Document all major changes in the CHANGELOG.md file.
- Update the README.md file with any new features or changes.
- Update CLAUDE.md with any important changes or notes for future reference.
- use twelve-factor methodology for configuration management.
- use Ruff for linting and code quality checks.
- use pytest for testing.


## Notes

### References for Writing Good README Files and CLI Best Practices

https://www.freecodecamp.org/news/how-to-write-a-good-readme-file/
https://clig.dev/#guidelines
https://medium.com/@jdxcode/12-factor-cli-apps-dd3c227a0e46
https://dev.to/wesen/14-great-tips-to-make-amazing-cli-applications-3gp3
https://versent.com.au/blog/writing-a-good-readme-md-file/
https://www.tilburgsciencehub.com/topics/collaborate-share/share-your-work/content-creation/readme-best-practices/
https://github.com/arturtamborski/cli-best-practices
https://medium.com/@kc_clintone/the-ultimate-guide-to-writing-a-great-readme-md-for-your-project-3d49c2023357
https://no-color.org/

### Alternative Geocoding Services

https://photon.komoot.io/
https://pelias.io/
https://addok.readthedocs.io/en/latest/
https://developers.google.com/maps/documentation
https://opencagedata.com/
https://nominatim.org/release-docs/develop/api/Overview/
https://geocode.maps.co/
https://www.gisgraphy.com/index.php