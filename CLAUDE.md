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

## Important Notes

- The `sample.csv` file is gitignored and contains voter registration data. Do not commit voter data files to version control.
- PostGIS database integration will be required for the spatial operations (not yet implemented)
