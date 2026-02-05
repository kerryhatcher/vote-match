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
Cloudflare R2 is used for hosting web maps and static files. https://developers.cloudflare.com/r2/

### Perfered Packages

- pandas
- loguru
- typer
- Jinja2


## Workflow

### Typical Usage

Vote Match processes voter registration data through several stages:

#### 1. Initialize Database

Create the database schema and PostGIS extension:

```bash
vote-match init-db
```

#### 2. Load Voter Data

Import voter registration CSV file:

```bash
vote-match load-csv sample.csv
```

#### 3. Geocode Addresses

Geocode voter addresses using the Census geocoding service (or other services):

```bash
# Use Census geocoder (default, processes all ungeocoded voters)
vote-match geocode

# Use alternative geocoding service for no_match records
vote-match geocode --service nominatim

# List available geocoding services
vote-match geocode --service list
```

#### 4. Sync Results for QGIS

After geocoding, sync the best results to the Voter table for QGIS visualization:

```bash
# Sync best geocoding results to PostGIS geometry column
vote-match sync-geocode

# Force update all voters (including those with existing geometry)
vote-match sync-geocode --force
```

**Important**: The `sync-geocode` command is **required** for QGIS visualization. It:

- Selects the best geocoding result from all services (exact > interpolated > approximate)
- Updates the Voter table's PostGIS `geom` column
- Allows QGIS to display voter locations on a map

#### 5. Check Status

View geocoding progress and statistics:

```bash
vote-match status
```

#### 6. QGIS Visualization

After syncing, connect QGIS to your PostGIS database and add the `voters` layer to visualize geocoded voter locations.

### Cascading Geocoding Strategy

Vote Match supports multiple geocoding services with a cascading approach:

1. **Census (Primary)**: Processes all ungeocoded voters
2. **Alternative Services**: Process only `no_match` records from previous attempts
3. **Best Result Selection**: Automatically selects highest quality result across all services

Example workflow:

```bash
# Step 1: Geocode with Census (primary service)
vote-match geocode --service census

# Step 2: Try Nominatim for no_match records
vote-match geocode --service nominatim

# Step 3: Sync best results to QGIS
vote-match sync-geocode

# Step 4: Check results
vote-match status
```

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

### Geocoding Services

Vote Match supports multiple geocoding services with different characteristics:

| Service       | Type       | Coverage  | Cost | Batch Support | API Key Required | Notes                                                         |
| ------------- | ---------- | --------- | ---- | ------------- | ---------------- | ------------------------------------------------------------- |
| **census**    | BATCH      | US only   | Free | Yes (CSV)     | No               | US Census Batch Geocoder - Primary service for US addresses  |
| **geocodio**  | BATCH      | US/Canada | Paid | Yes (10,000)  | Yes              | Excellent batch support and accuracy                          |
| **mapbox**    | BATCH      | Global    | Paid | Yes (1,000)   | Yes              | Mapbox Geocoding API v6 with global coverage                  |
| **nominatim** | INDIVIDUAL | Global    | Free | No            | No               | OpenStreetMap-based, 1 req/sec rate limit, requires email     |
| **photon**    | INDIVIDUAL | Global    | Free | No            | No               | Komoot/OSM-based, 1 req/sec recommended                       |
| **google**    | INDIVIDUAL | Global    | Paid | No            | Yes              | Google Maps Geocoding API - Premium quality, expensive        |

**Configuration:**

All services are configured via environment variables. See [.env.example](.env.example) for configuration details.

**Cost Considerations:**

- **Free**: census, nominatim, photon
- **Paid**: geocodio ($0.0005-$0.002 per lookup), mapbox ($0.0005 per lookup), google ($0.005 per lookup)

**Additional Resources:**

Other geocoding services that could be added in the future:

- Pelias: <https://pelias.io/>
- Addok: <https://addok.readthedocs.io/en/latest/>
- OpenCage: <https://opencagedata.com/>
- Geocode Maps: <https://geocode.maps.co/>
- Gisgraphy: <https://www.gisgraphy.com/index.php>



## Web Map
Use the following colors: 

1 #377eb8
2 #efa710
3 #c6b0d8
4 #f2c25a
5 #e20000
6 #f96060
7 #8a664a
8 #2d802f
9 #930eb4