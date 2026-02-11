"""County linking module for associating districts with counties.

This module provides functions to link district boundaries with county names using:
1. CSV mapping files (authoritative source for Georgia)
2. PostGIS spatial joins (automatic for any state)
3. Validation to compare CSV vs spatial results
"""

import csv
import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from geoalchemy2.functions import ST_Intersects

from .models import DistrictBoundary

logger = logging.getLogger(__name__)


def normalize_county_name(name: str) -> str:
    """Normalize county name to uppercase and strip 'County' suffix.

    Args:
        name: County name (e.g., "Bibb County", "BIBB", "Bibb")

    Returns:
        Normalized uppercase name without "County" suffix (e.g., "BIBB")
    """
    name = name.strip().upper()
    if name.endswith(" COUNTY"):
        name = name[:-7].strip()
    return name


def parse_district_list(district_str: str) -> list[str]:
    """Parse comma-separated district IDs from CSV.

    Args:
        district_str: District IDs as string (e.g., "2, 8" or "14")

    Returns:
        List of district IDs with whitespace trimmed
    """
    if not district_str or district_str.strip() == "":
        return []
    # Split by comma and strip whitespace from each ID
    return [d.strip() for d in district_str.split(",") if d.strip()]


def normalize_district_id(district_id: str, width: int = 3) -> str:
    """Normalize district ID with zero-padding.

    Args:
        district_id: District ID as string (e.g., "19", "8", "157")
        width: Width for zero-padding (default: 3)

    Returns:
        Zero-padded district ID (e.g., "019", "008", "157")
    """
    return district_id.zfill(width)


def link_districts_from_csv(
    session: Session,
    csv_path: Path,
    overwrite: bool = False,
) -> dict[str, int]:
    """Link districts to counties using CSV mapping file.

    The CSV format should be:
    County,Congressional Districts,Senate Districts,House Districts

    For districts spanning multiple counties, this function appends county names
    to create a comma-separated list (e.g., "BIBB, MONROE, JONES").

    Args:
        session: SQLAlchemy session
        csv_path: Path to counties-by-districts CSV file
        overwrite: If True, overwrite existing county_name values

    Returns:
        Dictionary with statistics:
            - updated: Number of district records updated
            - not_found: Number of district IDs from CSV not found in database
            - skipped: Number of records skipped (already have county_name)
            - errors: Number of errors encountered
    """
    logger.info(f"Loading CSV mapping from {csv_path}")

    stats = {"updated": 0, "not_found": 0, "skipped": 0, "errors": 0}

    # Map CSV column names to district types
    column_to_district_type = {
        "Congressional Districts": "congressional",
        "Senate Districts": "state_senate",
        "House Districts": "state_house",
    }

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                county_name = normalize_county_name(row["County"])

                # Process each district type column
                for csv_column, district_type in column_to_district_type.items():
                    district_ids = parse_district_list(row.get(csv_column, ""))

                    for district_id in district_ids:
                        try:
                            # Normalize district ID with zero-padding to match database format
                            normalized_id = normalize_district_id(district_id)

                            # Find the district in database
                            stmt = select(DistrictBoundary).where(
                                DistrictBoundary.district_type == district_type,
                                DistrictBoundary.district_id == normalized_id,
                            )
                            district = session.execute(stmt).scalar_one_or_none()

                            if not district:
                                logger.warning(f"District not found: {district_type} {district_id}")
                                stats["not_found"] += 1
                                continue

                            # Skip if already has county_name (unless overwrite)
                            if district.county_name and not overwrite:
                                # Append county if not already listed
                                if county_name not in district.county_name.split(", "):
                                    district.county_name = f"{district.county_name}, {county_name}"
                                    stats["updated"] += 1
                                    logger.debug(
                                        f"Appended county {county_name} to {district_type} {district_id}"
                                    )
                                else:
                                    stats["skipped"] += 1
                            else:
                                # Set or overwrite county_name
                                if district.county_name:
                                    # Append if different county
                                    if county_name not in district.county_name.split(", "):
                                        district.county_name = (
                                            f"{district.county_name}, {county_name}"
                                        )
                                else:
                                    district.county_name = county_name

                                stats["updated"] += 1
                                logger.debug(
                                    f"Linked {district_type} {district_id} to county {county_name}"
                                )

                        except Exception as e:
                            logger.error(f"Error processing {district_type} {district_id}: {e}")
                            stats["errors"] += 1

            # Commit changes
            session.commit()
            logger.info(f"CSV linking completed: {stats}")

    except Exception as e:
        logger.error(f"Failed to process CSV file: {e}")
        session.rollback()
        stats["errors"] += 1

    return stats


def link_districts_spatial(
    session: Session,
    district_type: Optional[str] = None,
    state_fips: Optional[str] = None,
    overwrite: bool = False,
) -> dict[str, int]:
    """Link districts to counties using PostGIS spatial joins.

    This function finds all counties that spatially intersect each district
    and updates the county_name column with a comma-separated list.

    Args:
        session: SQLAlchemy session
        district_type: Specific district type to process (None = all except county)
        state_fips: State FIPS code to filter counties (e.g., "13" for Georgia)
        overwrite: If True, overwrite existing county_name values

    Returns:
        Dictionary with statistics:
            - updated: Number of district records updated
            - skipped: Number of records skipped (already have county_name)
            - no_overlap: Number of districts with no county overlap
            - errors: Number of errors encountered
    """
    logger.info(f"Starting spatial linking for district_type={district_type}")

    stats = {"updated": 0, "skipped": 0, "no_overlap": 0, "errors": 0}

    try:
        # Query all districts (exclude county type itself)
        stmt = select(DistrictBoundary).where(DistrictBoundary.district_type != "county")

        if district_type:
            stmt = stmt.where(DistrictBoundary.district_type == district_type)

        districts = session.execute(stmt).scalars().all()

        logger.info(f"Processing {len(districts)} districts")

        for district in districts:
            # Skip if already has county_name (unless overwrite)
            if district.county_name and not overwrite:
                stats["skipped"] += 1
                continue

            try:
                # Find all counties that intersect this district
                county_stmt = (
                    select(DistrictBoundary.name)
                    .where(
                        DistrictBoundary.district_type == "county",
                        ST_Intersects(DistrictBoundary.geom, district.geom),
                    )
                    .order_by(DistrictBoundary.name)
                )

                # Filter by state FIPS if provided
                if state_fips:
                    county_stmt = county_stmt.where(
                        DistrictBoundary.extra_properties["STATEFP"].astext == state_fips
                    )

                counties = session.execute(county_stmt).scalars().all()

                if not counties:
                    logger.debug(
                        f"No county overlap for {district.district_type} {district.district_id}"
                    )
                    stats["no_overlap"] += 1
                    continue

                # Normalize and join county names
                county_names = [normalize_county_name(c) for c in counties]
                district.county_name = ", ".join(county_names)

                stats["updated"] += 1
                logger.debug(
                    f"Linked {district.district_type} {district.district_id} to counties: {district.county_name}"
                )

            except Exception as e:
                logger.error(
                    f"Error processing {district.district_type} {district.district_id}: {e}"
                )
                stats["errors"] += 1

        # Commit changes
        session.commit()
        logger.info(f"Spatial linking completed: {stats}")

    except Exception as e:
        logger.error(f"Spatial linking failed: {e}")
        session.rollback()
        stats["errors"] += 1

    return stats


def validate_county_links(
    session: Session, csv_path: Path, district_type: Optional[str] = None
) -> dict:
    """Compare CSV mappings vs spatial joins to identify mismatches.

    Args:
        session: SQLAlchemy session
        csv_path: Path to counties-by-districts CSV file
        district_type: Specific district type to validate (None = all)

    Returns:
        Dictionary with validation results:
            - matches: Number of matching associations
            - mismatches: Number of mismatches
            - csv_only: Districts in CSV but not in spatial results
            - spatial_only: Districts in spatial but not in CSV
            - details: List of mismatch details
    """
    logger.info(f"Validating county links from {csv_path}")

    results = {
        "matches": 0,
        "mismatches": 0,
        "csv_only": 0,
        "spatial_only": 0,
        "details": [],
    }

    # Build CSV mapping
    csv_mapping = {}  # {(district_type, district_id): set(county_names)}

    column_to_district_type = {
        "Congressional Districts": "congressional",
        "Senate Districts": "state_senate",
        "House Districts": "state_house",
    }

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            county_name = normalize_county_name(row["County"])

            for csv_column, dt in column_to_district_type.items():
                if district_type and dt != district_type:
                    continue

                district_ids = parse_district_list(row.get(csv_column, ""))
                for dist_id in district_ids:
                    # Normalize district ID with zero-padding
                    normalized_id = normalize_district_id(dist_id)
                    key = (dt, normalized_id)
                    if key not in csv_mapping:
                        csv_mapping[key] = set()
                    csv_mapping[key].add(county_name)

    # Query spatial results from database
    stmt = select(DistrictBoundary).where(
        DistrictBoundary.district_type.in_(column_to_district_type.values())
    )
    if district_type:
        stmt = stmt.where(DistrictBoundary.district_type == district_type)

    districts = session.execute(stmt).scalars().all()

    for district in districts:
        key = (district.district_type, district.district_id)
        csv_counties = csv_mapping.get(key, set())

        # Get spatial counties from county_name field
        if district.county_name:
            spatial_counties = set(c.strip() for c in district.county_name.split(","))
        else:
            spatial_counties = set()

        # Compare
        if csv_counties == spatial_counties:
            results["matches"] += 1
        else:
            results["mismatches"] += 1
            results["details"].append(
                {
                    "district_type": district.district_type,
                    "district_id": district.district_id,
                    "csv_counties": sorted(csv_counties),
                    "spatial_counties": sorted(spatial_counties),
                    "csv_only": sorted(csv_counties - spatial_counties),
                    "spatial_only": sorted(spatial_counties - csv_counties),
                }
            )

    # Count districts in CSV but not in database
    db_keys = {(d.district_type, d.district_id) for d in districts}
    results["csv_only"] = len(csv_mapping.keys() - db_keys)

    logger.info(
        f"Validation completed: {results['matches']} matches, {results['mismatches']} mismatches"
    )

    return results
