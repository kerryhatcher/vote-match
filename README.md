# Vote Mtch
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

### Perfered Packages

- pandas
- loguru
- typer


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
- 