"""Processing functions for geocoding voter records."""

import hashlib
import json
from pathlib import Path
from typing import Optional

from geoalchemy2 import WKTElement
from loguru import logger
from shapely.geometry import shape
from sqlalchemy import case, func, or_, text
from sqlalchemy.orm import Session

from vote_match.config import Settings
from vote_match.geocoder import GeocodeResult, build_batch_csv, parse_response, submit_batch
from vote_match.geocoding.base import GeocodeService, StandardGeocodeResult
from vote_match.models import (
    DISTRICT_TYPES,
    CountyCommissionDistrict,
    DistrictBoundary,
    VoterDistrictAssignment,
)
from vote_match.models import GeocodeResult as GeocodeResultModel
from vote_match.models import Voter
from vote_match.usps_validator import USPSValidationResult, validate_batch


def get_pending_voters(
    session: Session,
    limit: int | None = None,
    retry_failed: bool = False,
    retry_no_match: bool = False,
) -> list[Voter]:
    """
    Query voters that need geocoding.

    Args:
        session: SQLAlchemy session.
        limit: Maximum number of voters to retrieve (None for all).
        retry_failed: If True, also include voters with geocode_status='failed'.
        retry_no_match: If True, also include voters with geocode_status='no_match'.

    Returns:
        List of Voter objects that need geocoding.
    """
    query = session.query(Voter)

    # Build filter conditions for geocode status
    conditions = [Voter.geocode_status.is_(None)]  # Always include NULL (never geocoded)

    if retry_failed:
        conditions.append(Voter.geocode_status == "failed")

    if retry_no_match:
        conditions.append(Voter.geocode_status == "no_match")

    # Apply OR filter to include any matching condition
    query = query.filter(or_(*conditions))

    # Order by registration number for consistent ordering
    query = query.order_by(Voter.voter_registration_number)

    # Apply limit if specified
    if limit is not None:
        query = query.limit(limit)

    voters = query.all()
    logger.info(
        "Found {} pending voters (retry_failed={}, retry_no_match={})",
        len(voters),
        retry_failed,
        retry_no_match,
    )

    return voters


def apply_geocode_results(
    session: Session,
    results: list[GeocodeResult],
) -> int:
    """
    Apply geocoding results to voter records in the database.

    Args:
        session: SQLAlchemy session.
        results: List of GeocodeResult objects to apply.

    Returns:
        Count of updated records.
    """
    updated_count = 0

    for result in results:
        # Find voter by registration number
        voter = (
            session.query(Voter)
            .filter(Voter.voter_registration_number == result.registration_number)
            .first()
        )

        if not voter:
            logger.warning("Voter {} not found in database", result.registration_number)
            continue

        # Update geocoding fields
        voter.geocode_status = result.status
        voter.geocode_match_type = result.match_type
        voter.geocode_matched_address = result.matched_address
        voter.geocode_longitude = result.longitude
        voter.geocode_latitude = result.latitude
        voter.geocode_tigerline_id = result.tigerline_id
        voter.geocode_tigerline_side = result.tigerline_side
        voter.geocode_state_fips = result.state_fips
        voter.geocode_county_fips = result.county_fips
        voter.geocode_tract = result.tract
        voter.geocode_block = result.block

        # Create PostGIS geometry if coordinates are present
        if result.longitude is not None and result.latitude is not None:
            wkt = f"POINT({result.longitude} {result.latitude})"
            voter.geom = WKTElement(wkt, srid=4326)
            logger.debug(
                "Created geometry for voter {}: ({}, {})",
                result.registration_number,
                result.longitude,
                result.latitude,
            )
        else:
            voter.geom = None

        updated_count += 1

    # Commit all updates
    session.commit()
    logger.info("Updated {} voter records with geocoding results", updated_count)

    return updated_count


def process_geocoding(
    session: Session,
    settings: Settings,
    batch_size: int = 10000,
    limit: int | None = None,
    retry_failed: bool = False,
    retry_no_match: bool = False,
) -> dict:
    """
    Process geocoding for pending voter records.

    This function:
    1. Retrieves pending voters from database
    2. Splits them into batches for Census API
    3. Geocodes each batch
    4. Applies results back to database
    5. Returns summary statistics

    Args:
        session: SQLAlchemy session.
        settings: Application settings.
        batch_size: Records per Census API call (max 10000).
        limit: Total records to process (None for all pending).
        retry_failed: If True, retry previously failed records.
        retry_no_match: If True, retry records with no geocoding match.

    Returns:
        Dictionary with statistics:
        - total_processed: Total records processed
        - matched: Successfully geocoded records
        - no_match: Records that couldn't be geocoded
        - failed: Records that encountered errors
    """
    # Validate batch size
    if batch_size > 10000:
        logger.warning("Batch size {} exceeds Census API limit, using 10000", batch_size)
        batch_size = 10000

    # Initialize statistics
    stats = {
        "total_processed": 0,
        "matched": 0,
        "no_match": 0,
        "failed": 0,
    }

    # Get pending voters
    voters = get_pending_voters(
        session, limit=limit, retry_failed=retry_failed, retry_no_match=retry_no_match
    )

    if not voters:
        logger.info("No pending voters to geocode")
        return stats

    logger.info("Processing {} voters in batches of {}", len(voters), batch_size)

    # Process in batches
    for i in range(0, len(voters), batch_size):
        batch = voters[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(voters) + batch_size - 1) // batch_size

        logger.info("Processing batch {}/{} ({} records)", batch_num, total_batches, len(batch))

        try:
            # Build CSV for this batch
            csv_content = build_batch_csv(batch)

            # Submit to Census API
            response_text = submit_batch(csv_content, settings)

            # Parse response
            results = parse_response(response_text)

            # Apply results to database
            apply_geocode_results(session, results)

            # Update statistics
            stats["total_processed"] += len(results)
            for result in results:
                if result.status == "matched":
                    stats["matched"] += 1
                elif result.status == "no_match":
                    stats["no_match"] += 1
                else:
                    stats["failed"] += 1

            logger.info(
                "Batch {}/{} completed: {} matched, {} no_match, {} failed",
                batch_num,
                total_batches,
                sum(1 for r in results if r.status == "matched"),
                sum(1 for r in results if r.status == "no_match"),
                sum(1 for r in results if r.status == "failed"),
            )

        except Exception as e:
            # On error, mark entire batch as failed
            logger.error("Batch {}/{} failed: {}", batch_num, total_batches, str(e))

            for voter in batch:
                voter.geocode_status = "failed"
                stats["failed"] += 1

            session.commit()
            stats["total_processed"] += len(batch)

    logger.info(
        "Geocoding complete: {} total, {} matched, {} no_match, {} failed",
        stats["total_processed"],
        stats["matched"],
        stats["no_match"],
        stats["failed"],
    )

    return stats


def get_pending_usps_validation_voters(
    session: Session,
    limit: int | None = None,
    retry_failed: bool = False,
) -> list[Voter]:
    """
    Query voters that need USPS validation.

    Targets voters with failed geocoding that haven't been USPS validated yet.

    Args:
        session: SQLAlchemy session.
        limit: Maximum number of voters to retrieve (None for all).
        retry_failed: If True, also include voters with usps_validation_status='failed'.

    Returns:
        List of Voter objects that need USPS validation.
    """
    query = session.query(Voter)

    # Target voters with failed geocoding
    geocode_conditions = [
        Voter.geocode_status == "no_match",
        Voter.geocode_status == "failed",
    ]
    query = query.filter(or_(*geocode_conditions))

    # Build filter conditions for USPS validation status
    usps_conditions = [Voter.usps_validation_status.is_(None)]  # Always include NULL

    if retry_failed:
        usps_conditions.append(Voter.usps_validation_status == "failed")

    # Apply USPS validation filter
    query = query.filter(or_(*usps_conditions))

    # Order by registration number for consistent ordering
    query = query.order_by(Voter.voter_registration_number)

    # Apply limit if specified
    if limit is not None:
        query = query.limit(limit)

    voters = query.all()
    logger.info(
        "Found {} pending USPS validation voters (retry_failed={})",
        len(voters),
        retry_failed,
    )

    return voters


def apply_usps_validation_results(
    session: Session,
    results: list[USPSValidationResult],
) -> int:
    """
    Apply USPS validation results to voter records in the database.

    Args:
        session: SQLAlchemy session.
        results: List of USPSValidationResult objects to apply.

    Returns:
        Count of updated records.
    """
    updated_count = 0

    for result in results:
        # Find voter by registration number
        voter = (
            session.query(Voter)
            .filter(Voter.voter_registration_number == result.registration_number)
            .first()
        )

        if not voter:
            logger.warning("Voter {} not found in database", result.registration_number)
            continue

        # Update USPS validation fields
        voter.usps_validation_status = result.status
        voter.usps_validated_street_address = result.street_address
        voter.usps_validated_city = result.city
        voter.usps_validated_state = result.state
        voter.usps_validated_zipcode = result.zipcode
        voter.usps_validated_zipplus4 = result.zipplus4
        voter.usps_delivery_point = result.delivery_point
        voter.usps_carrier_route = result.carrier_route
        voter.usps_dpv_confirmation = result.dpv_confirmation
        voter.usps_business = result.business
        voter.usps_vacant = result.vacant

        updated_count += 1

        logger.debug(
            "Updated USPS validation for voter {}: status={}",
            result.registration_number,
            result.status,
        )

    # Commit all updates
    session.commit()
    logger.info("Updated {} voter records with USPS validation results", updated_count)

    return updated_count


def process_usps_validation(
    session: Session,
    settings: Settings,
    limit: int | None = None,
    retry_failed: bool = False,
) -> dict:
    """
    Process USPS validation for voters with failed geocoding.

    This function:
    1. Retrieves voters with failed geocoding from database
    2. Validates addresses with USPS API
    3. Applies results back to database
    4. Returns summary statistics

    Args:
        session: SQLAlchemy session.
        settings: Application settings.
        limit: Total records to process (None for all pending).
        retry_failed: If True, retry previously failed validations.

    Returns:
        Dictionary with statistics:
        - total_processed: Total records processed
        - validated: Addresses validated as-is
        - corrected: Addresses corrected by USPS
        - failed: Records that encountered errors
    """
    # Initialize statistics
    stats = {
        "total_processed": 0,
        "validated": 0,
        "corrected": 0,
        "failed": 0,
    }

    # Get pending voters
    voters = get_pending_usps_validation_voters(
        session,
        limit=limit,
        retry_failed=retry_failed,
    )

    if not voters:
        logger.info("No pending voters for USPS validation")
        return stats

    logger.info("Processing {} voters for USPS validation", len(voters))

    try:
        # Validate batch
        results = validate_batch(voters, settings)

        # Apply results to database
        apply_usps_validation_results(session, results)

        # Update statistics
        stats["total_processed"] = len(results)
        for result in results:
            if result.status == "validated":
                stats["validated"] += 1
            elif result.status == "corrected":
                stats["corrected"] += 1
            else:
                stats["failed"] += 1

        logger.info(
            "USPS validation complete: {} total, {} validated, {} corrected, {} failed",
            stats["total_processed"],
            stats["validated"],
            stats["corrected"],
            stats["failed"],
        )

    except Exception as e:
        # On error, mark entire batch as failed
        logger.error("USPS validation batch failed: {}", str(e))

        for voter in voters:
            voter.usps_validation_status = "failed"
            stats["failed"] += 1

        session.commit()
        stats["total_processed"] = len(voters)

    return stats


# ====================================================================
# NEW MULTI-SERVICE GEOCODING FUNCTIONS
# ====================================================================


def get_voters_for_geocoding(
    session: Session,
    service_name: str,
    limit: Optional[int] = None,
    only_unmatched: bool = True,
    retry_failed: bool = False,
) -> list[Voter]:
    """Get voters that need geocoding from specified service.

    Implements cascading strategy:
    - Census (only_unmatched=False): Find voters with NO results at all
    - Other services (only_unmatched=True): Find voters where best result
      from ANY service is no_match/failed, AND they haven't been processed
      by THIS specific service yet

    Args:
        session: SQLAlchemy session
        service_name: Name of the geocoding service
        limit: Maximum number of voters to return
        only_unmatched: If True, only return voters with no_match/failed from ANY service
                       If False, only return voters with no results at all
        retry_failed: If True, include voters with failed status

    Returns:
        List of Voter objects needing geocoding
    """
    query = session.query(Voter)

    if only_unmatched:
        # CASCADING STRATEGY: Find voters with no successful geocode from ANY service
        # Subquery to get best result status for each voter
        best_status_subquery = (
            session.query(
                GeocodeResultModel.voter_id,
                func.min(
                    case(
                        (GeocodeResultModel.status == "exact", 1),
                        (GeocodeResultModel.status == "interpolated", 2),
                        (GeocodeResultModel.status == "approximate", 3),
                        (GeocodeResultModel.status == "no_match", 4),
                        (GeocodeResultModel.status == "failed", 5),
                        else_=6,
                    )
                ).label("best_quality"),
            )
            .group_by(GeocodeResultModel.voter_id)
            .subquery()
        )

        # Join with subquery
        query = query.outerjoin(
            best_status_subquery,
            Voter.voter_registration_number == best_status_subquery.c.voter_id,
        )

        if retry_failed:
            # Include voters with no_match OR failed as best result
            query = query.filter(
                or_(
                    best_status_subquery.c.best_quality.is_(None),  # No results at all
                    best_status_subquery.c.best_quality >= 4,  # no_match or failed
                )
            )
        else:
            # Only include voters with no_match as best result (not failed)
            query = query.filter(
                or_(
                    best_status_subquery.c.best_quality.is_(None),  # No results at all
                    best_status_subquery.c.best_quality == 4,  # no_match only
                )
            )

        # Exclude voters already processed by THIS specific service
        this_service_subquery = (
            session.query(GeocodeResultModel.voter_id)
            .filter(GeocodeResultModel.service_name == service_name)
            .subquery()
        )
        query = query.outerjoin(
            this_service_subquery,
            Voter.voter_registration_number == this_service_subquery.c.voter_id,
        )
        query = query.filter(this_service_subquery.c.voter_id.is_(None))

    else:
        # DEFAULT STRATEGY (Census): Find voters with NO geocoding results at all
        any_result_subquery = session.query(GeocodeResultModel.voter_id).distinct().subquery()
        query = query.outerjoin(
            any_result_subquery,
            Voter.voter_registration_number == any_result_subquery.c.voter_id,
        )
        query = query.filter(any_result_subquery.c.voter_id.is_(None))

    # Order consistently
    query = query.order_by(Voter.voter_registration_number)

    if limit:
        query = query.limit(limit)

    voters = query.all()

    if only_unmatched:
        logger.info(
            f"Found {len(voters)} voters needing geocoding with {service_name} "
            f"(only unmatched, retry_failed={retry_failed})"
        )
    else:
        logger.info(f"Found {len(voters)} voters with no geocoding results for {service_name}")

    return voters


def save_geocode_results(session: Session, results: list[StandardGeocodeResult]) -> int:
    """Save geocoding results to the database.

    Args:
        session: SQLAlchemy session
        results: List of StandardGeocodeResult objects

    Returns:
        Count of saved records
    """
    saved_count = 0

    for result in results:
        # Create GeocodeResult model instance
        geocode_result = GeocodeResultModel(
            voter_id=result.voter_id,
            service_name=result.service_name,
            status=result.status.value,
            longitude=result.longitude,
            latitude=result.latitude,
            matched_address=result.matched_address,
            match_confidence=result.match_confidence,
            raw_response=result.raw_response,
            error_message=result.error_message,
        )

        session.add(geocode_result)
        saved_count += 1

        logger.debug(
            f"Saved {result.service_name} result for voter {result.voter_id}: {result.status.value}"
        )

    session.commit()
    logger.info(f"Saved {saved_count} geocoding results to database")

    return saved_count


def process_geocoding_service(
    session: Session,
    service: GeocodeService,
    batch_size: int = 10000,
    limit: Optional[int] = None,
    only_unmatched: bool = True,
    retry_failed: bool = False,
) -> dict[str, int]:
    """Unified geocoding processing pipeline for any service.

    Args:
        session: SQLAlchemy session
        service: GeocodeService instance to use
        batch_size: Records per batch
        limit: Maximum total records to process
        only_unmatched: Only process voters with no successful match from any service
        retry_failed: Include voters with failed status

    Returns:
        Dictionary with statistics:
        - total: Total records processed
        - exact: Exact matches
        - interpolated: Interpolated matches
        - approximate: Approximate matches
        - no_match: No matches found
        - failed: Failed records
    """
    from vote_match.geocoding.base import GeocodeQuality

    # Initialize statistics
    stats = {
        "total": 0,
        "exact": 0,
        "interpolated": 0,
        "approximate": 0,
        "no_match": 0,
        "failed": 0,
    }

    # Get voters needing geocoding
    voters = get_voters_for_geocoding(
        session=session,
        service_name=service.service_name,
        limit=limit,
        only_unmatched=only_unmatched,
        retry_failed=retry_failed,
    )

    if not voters:
        logger.info(f"No voters to geocode with {service.service_name}")
        return stats

    logger.info(
        f"Processing {len(voters)} voters with {service.service_name} in batches of {batch_size}"
    )

    # Process in batches
    for i in range(0, len(voters), batch_size):
        batch = voters[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(voters) + batch_size - 1) // batch_size

        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} records)")

        try:
            # Geocode batch using service
            results = service.geocode_batch(batch)

            # Save results to database
            save_geocode_results(session, results)

            # Update statistics
            stats["total"] += len(results)
            for result in results:
                status = result.status.value
                if status in stats:
                    stats[status] += 1
                else:
                    stats["failed"] += 1

            logger.info(
                f"Batch {batch_num}/{total_batches} completed: "
                f"{sum(1 for r in results if r.status.value == 'exact')} exact, "
                f"{sum(1 for r in results if r.status.value == 'interpolated')} interpolated, "
                f"{sum(1 for r in results if r.status.value == 'approximate')} approximate, "
                f"{sum(1 for r in results if r.status.value == 'no_match')} no_match, "
                f"{sum(1 for r in results if r.status.value == 'failed')} failed"
            )

        except Exception as e:
            # On error, mark batch as failed
            logger.error(f"Batch {batch_num}/{total_batches} failed: {e}")

            # Create failed results for this batch
            failed_results = [
                StandardGeocodeResult(
                    voter_id=voter.voter_registration_number,
                    service_name=service.service_name,
                    status=GeocodeQuality.FAILED,
                    longitude=None,
                    latitude=None,
                    matched_address=None,
                    match_confidence=None,
                    raw_response={},
                    error_message=str(e),
                )
                for voter in batch
            ]

            save_geocode_results(session, failed_results)
            stats["failed"] += len(batch)
            stats["total"] += len(batch)

    logger.info(
        f"Geocoding complete with {service.service_name}: "
        f"{stats['total']} total, "
        f"{stats['exact']} exact, "
        f"{stats['interpolated']} interpolated, "
        f"{stats['approximate']} approximate, "
        f"{stats['no_match']} no_match, "
        f"{stats['failed']} failed"
    )

    return stats


def sync_best_geocode_to_voters(
    session: Session,
    limit: Optional[int] = None,
    force_update: bool = False,
    update_legacy_fields: bool = True,
) -> dict[str, int]:
    """Sync best geocoding result to Voter table for QGIS display.

    This function updates the Voter table's geom column (and optionally
    legacy geocode_* fields) with the best geocoding result from the
    GeocodeResult table. Required for QGIS visualization.

    Args:
        session: SQLAlchemy session
        limit: Maximum number of voters to process (None for all)
        force_update: If True, update even if geom already exists
        update_legacy_fields: If True, also update legacy geocode_* fields

    Returns:
        Dictionary with statistics:
        - total_processed: Voters examined
        - updated: Voters with geometry updated
        - skipped_no_results: Voters with no geocode results
        - skipped_no_coords: Voters with results but no coordinates
        - skipped_already_set: Voters with geom already set (force_update=False)
    """
    stats = {
        "total_processed": 0,
        "updated": 0,
        "skipped_no_results": 0,
        "skipped_no_coords": 0,
        "skipped_already_set": 0,
    }

    # Build query for voters with geocode results
    query = session.query(Voter)

    if not force_update:
        # Only process voters without geometry
        query = query.filter(Voter.geom.is_(None))

    # Order consistently
    query = query.order_by(Voter.voter_registration_number)

    if limit:
        query = query.limit(limit)

    voters = query.all()
    logger.info(
        f"Syncing best geocode results to {len(voters)} voters "
        f"(force_update={force_update}, update_legacy_fields={update_legacy_fields})"
    )

    for voter in voters:
        stats["total_processed"] += 1

        # Get best geocode result using model property
        best_result = voter.best_geocode_result

        if not best_result:
            stats["skipped_no_results"] += 1
            logger.debug(f"Voter {voter.voter_registration_number} has no geocode results")
            continue

        # Check if result has valid coordinates
        if best_result.longitude is None or best_result.latitude is None:
            stats["skipped_no_coords"] += 1
            logger.debug(
                f"Voter {voter.voter_registration_number} best result has no coordinates "
                f"(status={best_result.status})"
            )
            continue

        # Skip if already has geometry and not forcing update
        if not force_update and voter.geom is not None:
            stats["skipped_already_set"] += 1
            continue

        # Update geometry
        wkt = f"POINT({best_result.longitude} {best_result.latitude})"
        voter.geom = WKTElement(wkt, srid=4326)

        # Update legacy fields if requested
        if update_legacy_fields:
            voter.geocode_status = best_result.status
            voter.geocode_match_type = best_result.status  # Same as status for filtering
            voter.geocode_matched_address = best_result.matched_address
            voter.geocode_longitude = best_result.longitude
            voter.geocode_latitude = best_result.latitude

            # Note: Legacy fields like tigerline_id, FIPS codes, etc.
            # are Census-specific and stored in raw_response
            # We don't populate them here to keep it service-agnostic

        stats["updated"] += 1

        if stats["updated"] % 1000 == 0:
            logger.info(f"Progress: {stats['updated']} voters updated...")

    # Commit all updates
    session.commit()

    logger.info(
        f"Sync complete: {stats['updated']} updated, "
        f"{stats['skipped_no_results']} no results, "
        f"{stats['skipped_no_coords']} no coords, "
        f"{stats['skipped_already_set']} already set"
    )

    return stats


def import_geojson_districts(
    session: Session,
    file_path: Path,
    clear_existing: bool = False,
) -> dict[str, int]:
    """Import district boundaries from GeoJSON file.

    Args:
        session: Database session
        file_path: Path to GeoJSON file
        clear_existing: If True, delete all existing districts before importing

    Returns:
        Dictionary with statistics: total, success, failed, skipped

    Raises:
        FileNotFoundError: If GeoJSON file doesn't exist
        ValueError: If GeoJSON is invalid or missing required fields
    """
    if not file_path.exists():
        raise FileNotFoundError(f"GeoJSON file not found: {file_path}")

    logger.info(f"Importing districts from {file_path}")

    # Clear existing districts if requested
    if clear_existing:
        count = session.query(CountyCommissionDistrict).count()
        logger.info(f"Clearing {count} existing districts...")
        session.query(CountyCommissionDistrict).delete()
        session.commit()

    # Load GeoJSON
    with open(file_path) as f:
        geojson_data = json.load(f)

    if geojson_data.get("type") != "FeatureCollection":
        raise ValueError(
            f"Invalid GeoJSON: expected FeatureCollection, got {geojson_data.get('type')}"
        )

    features = geojson_data.get("features", [])
    if not features:
        raise ValueError("No features found in GeoJSON")

    logger.info(f"Found {len(features)} features to import")

    stats = {"total": len(features), "success": 0, "failed": 0, "skipped": 0}

    for idx, feature in enumerate(features, 1):
        try:
            properties = feature.get("properties", {})
            geometry = feature.get("geometry")

            if not geometry:
                logger.warning(f"Feature {idx}: Missing geometry, skipping")
                stats["skipped"] += 1
                continue

            # Extract required fields (handle multiple possible property name formats)
            district_id = properties.get("DISTRICTID") or properties.get("District")
            name = properties.get("NAME") or properties.get("Name")

            if not district_id or not name:
                logger.warning(f"Feature {idx}: Missing DISTRICTID/District or NAME/Name, skipping")
                stats["skipped"] += 1
                continue

            # Check if district already exists
            existing = (
                session.query(CountyCommissionDistrict).filter_by(district_id=district_id).first()
            )

            if existing:
                logger.debug(f"District {district_id} already exists, skipping")
                stats["skipped"] += 1
                continue

            # Convert GeoJSON geometry to PostGIS
            shapely_geom = shape(geometry)
            wkt = shapely_geom.wkt
            geom = WKTElement(wkt, srid=4326)

            # Create district record (handle multiple possible property name formats)
            district = CountyCommissionDistrict(
                district_id=district_id,
                name=name,
                rep_name=properties.get("REPNAME1") or properties.get("Commissioner"),
                party=properties.get("PARTY1") or properties.get("Party"),
                district_url=properties.get("DISTRICTURL1") or properties.get("District_URL"),
                email=properties.get("Email") or properties.get("E_Mail"),
                photo_url=properties.get("Photo") or properties.get("Photo_URL"),
                rep_name_2=properties.get("NAME2") or properties.get("Commissioner2"),
                object_id=properties.get("OBJECTID"),
                global_id=properties.get("GlobalID"),
                creation_date=None,  # Would need to parse date string if present
                creator=properties.get("Creator"),
                edit_date=None,  # Would need to parse date string if present
                editor=properties.get("Editor"),
                geom=geom,
            )

            session.add(district)
            stats["success"] += 1

            if stats["success"] % 100 == 0:
                logger.info(f"Progress: {stats['success']}/{len(features)} districts imported...")

        except Exception as e:
            logger.warning(f"Feature {idx}: Failed to import - {e}")
            stats["failed"] += 1

    # Commit all changes
    session.commit()

    logger.info(
        f"Import complete: {stats['success']} imported, "
        f"{stats['skipped']} skipped, "
        f"{stats['failed']} failed"
    )

    return stats


def compare_voter_districts(
    session: Session,
    limit: int | None = None,
) -> dict[str, int | list[dict]]:
    """Compare voter registration districts with spatially-determined districts.

    Uses PostGIS spatial joins to find which district polygon contains each
    voter's geocoded point location, then compares with their registered
    district.

    Args:
        session: Database session
        limit: Optional limit on number of voters to process

    Returns:
        Dictionary with:
        - statistics: total, matched, mismatched, no_location, no_district
        - mismatches: List of mismatch records (voter_id, registered, spatial)
    """
    from sqlalchemy import text

    logger.info("Starting voter district comparison")

    # Count total voters with geocoded locations
    total_with_geom = session.query(Voter).filter(Voter.geom.isnot(None)).count()
    logger.info(f"Found {total_with_geom} voters with geocoded locations")

    # Build query to find spatial district for each voter
    # Using ST_Within to find which district polygon contains the voter's point
    query = text(
        """
        SELECT
            v.voter_registration_number,
            v.first_name,
            v.last_name,
            v.middle_name,
            v.suffix,
            v.residence_street_number,
            v.residence_pre_direction,
            v.residence_street_name,
            v.residence_street_type,
            v.residence_post_direction,
            v.residence_apt_unit_number,
            v.residence_city,
            v.residence_zipcode,
            v.county_commission_district as registered_district,
            d.district_id as spatial_district,
            d.name as spatial_district_name,
            ST_AsText(v.geom) as voter_location,
            best_gr.service_name as geocode_service,
            best_gr.status as geocode_status,
            best_gr.match_confidence as geocode_confidence,
            best_gr.matched_address as geocode_matched_address,
            v.birth_year,
            v.race,
            v.gender,
            v.registration_date,
            v.last_party_voted,
            v.last_vote_date
        FROM voters v
        LEFT JOIN county_commission_districts d
            ON ST_Within(v.geom, d.geom)
        LEFT JOIN LATERAL (
            SELECT service_name, status, match_confidence, matched_address
            FROM geocode_results gr
            WHERE gr.voter_id = v.voter_registration_number
                AND gr.longitude IS NOT NULL
                AND gr.latitude IS NOT NULL
            ORDER BY
                CASE gr.status
                    WHEN 'exact' THEN 1
                    WHEN 'interpolated' THEN 2
                    WHEN 'approximate' THEN 3
                    WHEN 'no_match' THEN 4
                    WHEN 'failed' THEN 5
                    ELSE 6
                END,
                gr.match_confidence DESC NULLS LAST
            LIMIT 1
        ) best_gr ON true
        WHERE v.geom IS NOT NULL
        """
    )

    if limit:
        query = text(str(query) + f" LIMIT {limit}")

    logger.info("Executing spatial join query...")
    results = session.execute(query).fetchall()

    stats = {
        "total": len(results),
        "matched": 0,
        "mismatched": 0,
        "no_location": 0,
        "no_district": 0,
    }

    mismatches = []

    for row in results:
        voter_id = row[0]
        first_name = row[1]
        last_name = row[2]
        middle_name = row[3]
        suffix = row[4]
        street_number = row[5]
        pre_direction = row[6]
        street_name = row[7]
        street_type = row[8]
        post_direction = row[9]
        apt_unit = row[10]
        city = row[11]
        zipcode = row[12]
        registered_district = row[13]
        spatial_district = row[14]
        spatial_district_name = row[15]
        voter_location = row[16]
        geocode_service = row[17]
        geocode_status = row[18]
        geocode_confidence = row[19]
        geocode_matched_address = row[20]
        birth_year = row[21]
        race = row[22]
        gender = row[23]
        registration_date = row[24]
        last_party_voted = row[25]
        last_vote_date = row[26]

        # Build full address for convenience
        address_parts = [
            street_number,
            pre_direction,
            street_name,
            street_type,
            post_direction,
        ]
        full_address = " ".join(filter(None, address_parts))
        if apt_unit:
            full_address += f" {apt_unit}"
        if city:
            full_address += f", {city}"
        if zipcode:
            full_address += f" {zipcode}"

        # Build full name for convenience
        name_parts = [first_name, middle_name, last_name, suffix]
        full_name = " ".join(filter(None, name_parts))

        # Skip if we couldn't determine spatial district
        if not spatial_district:
            stats["no_district"] += 1
            continue

        # Skip if voter doesn't have a registered district
        if not registered_district:
            stats["no_district"] += 1
            continue

        # Compare districts (normalize to handle different formats)
        # Voter's county_commission_district might be like "District 1" or "1"
        # District ID might be like "1" or "01"
        registered_normalized = (
            registered_district.replace("District", "").replace("district", "").strip()
        )
        spatial_normalized = spatial_district.strip()

        if registered_normalized == spatial_normalized:
            stats["matched"] += 1
        else:
            stats["mismatched"] += 1
            mismatches.append(
                {
                    "voter_id": voter_id,
                    "full_name": full_name,
                    "first_name": first_name or "",
                    "last_name": last_name or "",
                    "middle_name": middle_name or "",
                    "suffix": suffix or "",
                    "birth_year": birth_year or "",
                    "race": race or "",
                    "gender": gender or "",
                    "registration_date": registration_date or "",
                    "last_party_voted": last_party_voted or "",
                    "last_vote_date": last_vote_date or "",
                    "residence_full_address": full_address,
                    "residence_street_number": street_number or "",
                    "residence_pre_direction": pre_direction or "",
                    "residence_street_name": street_name or "",
                    "residence_street_type": street_type or "",
                    "residence_post_direction": post_direction or "",
                    "residence_apt_unit_number": apt_unit or "",
                    "residence_city": city or "",
                    "residence_zipcode": zipcode or "",
                    "registered_district": registered_district,
                    "expected_district": spatial_district,
                    "spatial_district_name": spatial_district_name,
                    "geocode_service": geocode_service or "",
                    "geocode_status": geocode_status or "",
                    "geocode_confidence": geocode_confidence or "",
                    "geocode_matched_address": geocode_matched_address or "",
                    "location": voter_location,
                }
            )

        if (stats["matched"] + stats["mismatched"]) % 1000 == 0:
            logger.info(
                f"Progress: {stats['matched'] + stats['mismatched']}/{stats['total']} voters processed..."
            )

    logger.info(
        f"Comparison complete: {stats['matched']} matched, "
        f"{stats['mismatched']} mismatched, "
        f"{stats['no_district']} no district found"
    )

    return {
        "stats": stats,
        "mismatches": mismatches,
    }


def export_district_comparison(
    mismatches: list[dict],
    output_path: Path,
) -> None:
    """Export district comparison mismatches to CSV file.

    Args:
        mismatches: List of mismatch records from compare_voter_districts()
        output_path: Path to output CSV file
    """
    import csv

    logger.info(f"Exporting {len(mismatches)} mismatches to {output_path}")

    # Define field order for CSV (organized for elections board usability)
    fieldnames = [
        "voter_id",
        "full_name",
        "first_name",
        "last_name",
        "middle_name",
        "suffix",
        "birth_year",
        "race",
        "gender",
        "registration_date",
        "last_party_voted",
        "last_vote_date",
        "residence_full_address",
        "residence_street_number",
        "residence_pre_direction",
        "residence_street_name",
        "residence_street_type",
        "residence_post_direction",
        "residence_apt_unit_number",
        "residence_city",
        "residence_zipcode",
        "registered_district",
        "expected_district",
        "spatial_district_name",
        "geocode_service",
        "geocode_status",
        "geocode_confidence",
        "geocode_matched_address",
        "location",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        if mismatches:
            writer.writerows(mismatches)
            logger.info(f"Export complete: {len(mismatches)} records written to {output_path}")
        else:
            logger.info("No mismatches to export, wrote empty file with headers")


def update_voter_district_comparison(
    session: Session,
    clear_existing: bool = True,
    limit: int | None = None,
) -> dict[str, int]:
    """Update voters table with district comparison results.

    Compares voter registration districts with spatially-determined districts
    and updates the voters table with the results. This allows filtering
    mismatched voters directly in QGIS without joins.

    Args:
        session: Database session
        clear_existing: If True, clear previous comparison results before updating
        limit: Optional limit on number of voters to process (for testing)

    Returns:
        Dictionary with statistics:
        - total_compared: Total voters compared
        - matched: Voters whose districts matched
        - mismatched: Voters with district mismatches
        - no_district: Voters with no district found
        - records_updated: Total voter records updated
        - records_cleared: Records cleared (if clear_existing=True)
    """
    from datetime import datetime

    logger.info("Starting voter district comparison update")

    stats = {
        "total_compared": 0,
        "matched": 0,
        "mismatched": 0,
        "no_district": 0,
        "records_updated": 0,
        "records_cleared": 0,
    }

    # Clear existing comparison results if requested
    if clear_existing:
        # Count voters with existing results
        count = session.query(Voter).filter(Voter.district_compared_at.isnot(None)).count()

        if count > 0:
            logger.info(f"Clearing {count} existing comparison results...")
            session.query(Voter).update(
                {
                    Voter.spatial_district_id: None,
                    Voter.spatial_district_name: None,
                    Voter.district_mismatch: None,
                    Voter.district_compared_at: None,
                }
            )
            session.commit()
            stats["records_cleared"] = count

    # Run district comparison
    logger.info("Running district comparison...")
    result = compare_voter_districts(session=session, limit=limit)

    comparison_stats = result["stats"]

    stats["total_compared"] = comparison_stats["total"]
    stats["matched"] = comparison_stats["matched"]
    stats["mismatched"] = comparison_stats["mismatched"]
    stats["no_district"] = comparison_stats["no_district"]

    # Build lookup of all comparison results
    # We need to update ALL voters, not just mismatches
    comparison_timestamp = datetime.now()

    # Strategy: Use the raw SQL query results to update all voters
    # This is more efficient than individual updates
    from sqlalchemy import text

    # Build update query that sets comparison results for all voters
    update_query = text(
        """
        UPDATE voters v
        SET
            spatial_district_id = subq.spatial_district,
            spatial_district_name = subq.spatial_district_name,
            district_mismatch = subq.is_mismatch,
            district_compared_at = :compared_at
        FROM (
            SELECT
                v2.voter_registration_number,
                d.district_id as spatial_district,
                d.name as spatial_district_name,
                CASE
                    WHEN d.district_id IS NULL THEN NULL
                    WHEN v2.county_commission_district IS NULL THEN NULL
                    WHEN REPLACE(REPLACE(LOWER(v2.county_commission_district), 'district', ''), ' ', '')
                         != LOWER(TRIM(d.district_id))
                    THEN true
                    ELSE false
                END as is_mismatch
            FROM voters v2
            LEFT JOIN county_commission_districts d
                ON ST_Within(v2.geom, d.geom)
            WHERE v2.geom IS NOT NULL
            """
        + (f"LIMIT {limit}" if limit else "")
        + """
        ) subq
        WHERE v.voter_registration_number = subq.voter_registration_number
    """
    )

    logger.info("Updating voter records with comparison results...")
    result_proxy = session.execute(update_query, {"compared_at": comparison_timestamp})
    stats["records_updated"] = result_proxy.rowcount

    session.commit()

    logger.info(
        f"District comparison update complete: {stats['records_updated']} voters updated, "
        f"{stats['matched']} matched, {stats['mismatched']} mismatched, "
        f"{stats['no_district']} no district found"
    )

    return stats


def _get_voters_geojson(
    session: Session,
    limit: int | None = None,
    matched_only: bool = False,
    mismatch_only: bool = False,
    exact_match_only: bool = False,
    redact_pii: bool = False,
) -> dict:
    """
    Query voters as GeoJSON using PostGIS ST_AsGeoJSON.

    Args:
        session: SQLAlchemy session.
        limit: Maximum number of voters to include.
        matched_only: If True, only include voters with successful geocoding.
        mismatch_only: If True, only include voters with district mismatches.
        exact_match_only: If True, only include voters with exact geocode matches.
        redact_pii: If True, exclude PII fields (name, address, registration number).

    Returns:
        GeoJSON FeatureCollection dict.
    """
    logger.info("Querying voters for GeoJSON export...")

    # Build query with PostGIS ST_AsGeoJSON for direct geometry conversion
    if redact_pii:
        # Minimal query - no PII fields
        query_sql = """
            SELECT
                county_commission_district,
                spatial_district_id,
                district_mismatch,
                geocode_status,
                geocode_match_type,
                ST_AsGeoJSON(geom)::json as geometry
            FROM voters
            WHERE geom IS NOT NULL
        """
    else:
        # Full query with PII
        query_sql = """
            SELECT
                voter_registration_number,
                COALESCE(first_name || ' ' || last_name, 'Unknown') as full_name,
                COALESCE(
                    residence_street_number || ' ' ||
                    COALESCE(residence_pre_direction || ' ', '') ||
                    residence_street_name || ' ' ||
                    COALESCE(residence_street_type, ''),
                    'Unknown'
                ) as street_address,
                residence_city,
                status,
                county_commission_district,
                spatial_district_id,
                district_mismatch,
                geocode_status,
                geocode_match_type,
                ST_AsGeoJSON(geom)::json as geometry
            FROM voters
            WHERE geom IS NOT NULL
        """

    if matched_only:
        query_sql += " AND geocode_status IN ('exact', 'interpolated', 'approximate')"

    if mismatch_only:
        query_sql += " AND district_mismatch = true"

    if exact_match_only:
        query_sql += " AND geocode_match_type = 'exact'"

    query_sql += " ORDER BY voter_registration_number"

    if limit:
        query_sql += f" LIMIT {limit}"

    result = session.execute(text(query_sql))
    rows = result.fetchall()

    # Build GeoJSON FeatureCollection
    features = []
    for row in rows:
        if redact_pii:
            # Privacy mode - minimal properties
            feature = {
                "type": "Feature",
                "geometry": row.geometry,
                "properties": {
                    "county_commission_district": row.county_commission_district,
                    "spatial_district_id": row.spatial_district_id,
                    "district_mismatch": row.district_mismatch,
                    "geocode_status": row.geocode_status,
                    "geocode_match_type": row.geocode_match_type,
                },
            }
        else:
            # Full mode - all properties including PII
            feature = {
                "type": "Feature",
                "geometry": row.geometry,
                "properties": {
                    "voter_registration_number": row.voter_registration_number,
                    "full_name": row.full_name,
                    "street_address": row.street_address,
                    "residence_city": row.residence_city,
                    "status": row.status,
                    "county_commission_district": row.county_commission_district,
                    "spatial_district_id": row.spatial_district_id,
                    "district_mismatch": row.district_mismatch,
                    "geocode_status": row.geocode_status,
                    "geocode_match_type": row.geocode_match_type,
                },
            }
        features.append(feature)

    logger.info(f"Retrieved {len(features)} voters for GeoJSON export")

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def _get_districts_geojson(
    session: Session,
    district_type: str = "county_commission",
    mismatch_only: bool = False,
    exact_match_only: bool = False,
) -> dict:
    """
    Query districts as GeoJSON for any district type using PostGIS ST_AsGeoJSON.

    Args:
        session: SQLAlchemy session
        district_type: District type key from DISTRICT_TYPES (e.g., 'state_senate', 'congressional')
        mismatch_only: If True, only count voters with district mismatches
        exact_match_only: If True, only count voters with exact geocode matches

    Returns:
        GeoJSON FeatureCollection dict with properties:
            - voter_count: Total voters in district (by spatial join)
            - registered_elsewhere_count: Voters registered elsewhere but living here (filtered)
            - registered_here_elsewhere_count: Voters registered here but living elsewhere (filtered)
    """
    from vote_match.models import DISTRICT_TYPES

    logger.info(
        f"Querying {district_type} districts for GeoJSON export "
        f"(mismatch_only={mismatch_only}, exact_match_only={exact_match_only})..."
    )

    # Validate district type
    if district_type not in DISTRICT_TYPES:
        raise ValueError(f"Invalid district_type: {district_type}")

    # Build filter condition for mismatch counts
    filter_conditions = []
    if mismatch_only:
        filter_conditions.append("v.district_mismatch = true")
    if exact_match_only:
        filter_conditions.append("v.geocode_match_type = 'exact'")

    filter_sql = " AND " + " AND ".join(filter_conditions) if filter_conditions else ""

    # Build query using generic district_boundaries table and voter_district_assignments
    # voter_count: Total voters spatially located in this district
    # registered_elsewhere_count: Voters living here but registered elsewhere (mismatch = true)
    # registered_here_elsewhere_count: Voters registered here but living elsewhere
    query_sql = f"""
        SELECT
            d.district_id,
            d.name as district_name,
            d.rep_name as representative_name,
            d.party,
            d.email as contact_email,
            d.district_url as website,
            ST_AsGeoJSON(d.geom)::json as geometry,
            COUNT(CASE WHEN vda.spatial_district_id = d.district_id THEN 1 END) as voter_count,
            COUNT(CASE
                WHEN vda.spatial_district_id = d.district_id
                    AND vda.is_mismatch = true
                    {filter_sql}
                THEN 1
            END) as registered_elsewhere_count,
            COUNT(CASE
                WHEN vda.registered_value IS NOT NULL
                    AND (vda.spatial_district_id IS NULL OR vda.spatial_district_id != d.district_id)
                    {filter_sql}
                THEN 1
            END) as registered_here_elsewhere_count
        FROM district_boundaries d
        LEFT JOIN voter_district_assignments vda
            ON vda.district_type = :district_type
            AND (vda.spatial_district_id = d.district_id OR vda.registered_value IS NOT NULL)
        LEFT JOIN voters v ON v.voter_registration_number = vda.voter_id AND v.geom IS NOT NULL
        WHERE d.district_type = :district_type
        GROUP BY d.district_id, d.name, d.rep_name, d.party, d.email, d.district_url, d.geom
        ORDER BY d.district_id
    """

    result = session.execute(text(query_sql), {"district_type": district_type})
    rows = result.fetchall()

    # Build GeoJSON FeatureCollection
    features = []
    for row in rows:
        feature = {
            "type": "Feature",
            "geometry": row.geometry,
            "properties": {
                "district_id": row.district_id,
                "district_name": row.district_name,
                "representative_name": row.representative_name,
                "party": row.party,
                "contact_email": row.contact_email,
                "website": row.website,
                "voter_count": row.voter_count,
                "registered_elsewhere_count": row.registered_elsewhere_count,
                "registered_here_elsewhere_count": row.registered_here_elsewhere_count,
            },
        }
        features.append(feature)

    logger.info(f"Retrieved {len(features)} districts for GeoJSON export")

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def _calculate_map_bounds(voters_geojson: dict, districts_geojson: dict) -> list:
    """
    Calculate Leaflet map bounds from GeoJSON data.

    Args:
        voters_geojson: GeoJSON FeatureCollection of voters.
        districts_geojson: GeoJSON FeatureCollection of districts.

    Returns:
        Leaflet bounds array: [[south, west], [north, east]] or empty list if no data.
    """
    coords = []

    # Extract coordinates from voters (points)
    for feature in voters_geojson.get("features", []):
        geom = feature.get("geometry")
        if geom and geom.get("type") == "Point":
            lon, lat = geom.get("coordinates", [None, None])
            if lon is not None and lat is not None:
                coords.append((lat, lon))

    # Extract coordinates from districts (polygons/multipolygons)
    for feature in districts_geojson.get("features", []):
        geom = feature.get("geometry")
        if geom:
            if geom.get("type") == "Polygon":
                # Polygon: coordinates[0] is the outer ring
                for lon, lat in geom.get("coordinates", [[]])[0]:
                    coords.append((lat, lon))
            elif geom.get("type") == "MultiPolygon":
                # MultiPolygon: coordinates[i][0] is each polygon's outer ring
                for polygon in geom.get("coordinates", []):
                    for lon, lat in polygon[0]:
                        coords.append((lat, lon))

    if not coords:
        logger.warning("No coordinates found for map bounds calculation")
        return []

    # Calculate bounds
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]

    south = min(lats)
    north = max(lats)
    west = min(lons)
    east = max(lons)

    logger.info(f"Calculated map bounds: south={south}, north={north}, west={west}, east={east}")

    return [[south, west], [north, east]]


def generate_leaflet_map(
    session: Session,
    title: str = "Voter Registration Map",
    limit: int | None = None,
    include_districts: bool = False,
    matched_only: bool = False,
    mismatch_only: bool = False,
    exact_match_only: bool = False,
    output_path: Path | None = None,
    html_filename: str = "index.html",
    settings: Settings | None = None,
    redact_pii: bool = False,
    district_type: str | None = None,
) -> str:
    """
    Generate an interactive Leaflet map with separate GeoJSON files.

    Creates a web folder structure with:
    - {html_filename} - Main map page (default: index.html)
    - voters.{hash}.geojson - Voter data with cache-busting hash
    - districts.{hash}.geojson - District boundaries with cache-busting hash

    Args:
        session: SQLAlchemy session.
        title: Map title.
        limit: Maximum number of voters to include.
        include_districts: Whether to include district boundary layer.
        matched_only: If True, only include voters with successful geocoding.
        mismatch_only: If True, only include voters with district mismatches.
        exact_match_only: If True, only include voters with exact geocode matches.
        output_path: Path to output directory. If None, returns HTML as string.
        html_filename: Name of the HTML file to create (default: index.html).
        settings: Settings object (optional).
        redact_pii: If True, exclude PII fields from voter data.
        district_type: District type to display (e.g., 'state_senate', 'congressional').
                      Defaults to 'county_commission' if None.

    Returns:
        Path to the generated index.html file, or HTML string if output_path is None.
    """
    # Get settings if not provided
    if settings is None:
        from vote_match.config import get_settings

        settings = get_settings()

    logger.info(
        f"Generating Leaflet map: title='{title}', limit={limit}, include_districts={include_districts}, "
        f"mismatch_only={mismatch_only}, exact_match_only={exact_match_only}, redact_pii={redact_pii}"
    )

    # Query data as GeoJSON
    voters_geojson = _get_voters_geojson(
        session,
        limit=limit,
        matched_only=matched_only,
        mismatch_only=mismatch_only,
        exact_match_only=exact_match_only,
        redact_pii=redact_pii,
    )

    districts_geojson = {"type": "FeatureCollection", "features": []}
    if include_districts:
        districts_geojson = _get_districts_geojson(
            session,
            district_type=district_type or "county_commission",
            mismatch_only=mismatch_only,
            exact_match_only=exact_match_only,
        )

    # Calculate map bounds
    bounds = _calculate_map_bounds(voters_geojson, districts_geojson)

    # If output_path is provided, create web folder structure
    if output_path:
        # Create web directory
        web_dir = output_path if output_path.is_dir() else output_path.parent / "web"
        web_dir.mkdir(parents=True, exist_ok=True)

        # Generate voters GeoJSON with checksum
        voters_json = json.dumps(voters_geojson, separators=(",", ":"))
        voters_hash = hashlib.sha256(voters_json.encode()).hexdigest()[:8]
        voters_filename = f"voters.{voters_hash}.geojson"
        voters_path = web_dir / voters_filename
        voters_path.write_text(voters_json)
        logger.info(f"Saved voters GeoJSON: {voters_path}")

        # Generate districts GeoJSON with checksum (if applicable)
        districts_filename = None
        if include_districts and districts_geojson["features"]:
            districts_json = json.dumps(districts_geojson, separators=(",", ":"))
            districts_hash = hashlib.sha256(districts_json.encode()).hexdigest()[:8]
            districts_filename = f"districts.{districts_hash}.geojson"
            districts_path = web_dir / districts_filename
            districts_path.write_text(districts_json)
            logger.info(f"Saved districts GeoJSON: {districts_path}")

        # Load async HTML template
        template_path = Path(__file__).parent / "templates" / "leaflet_map_async.html"
        if not template_path.exists():
            msg = f"Template file not found: {template_path}"
            raise FileNotFoundError(msg)

        template_content = template_path.read_text()

        # Replace template variables
        html = template_content.replace("{{ title }}", title)
        html = html.replace("{{ bounds }}", json.dumps(bounds))
        # Clustering configuration
        html = html.replace("{{ enable_clustering }}", str(settings.map_enable_clustering).lower())
        html = html.replace("{{ cluster_max_zoom }}", str(settings.map_cluster_max_zoom))
        html = html.replace(
            "{{ spiderfy_distance_multiplier }}", str(settings.map_spiderfy_distance_multiplier)
        )
        html = html.replace(
            "{{ show_coverage_on_hover }}", str(settings.map_cluster_show_coverage_on_hover).lower()
        )
        # Cluster zoom settings
        html = html.replace("{{ cluster_zoom_far }}", str(settings.map_cluster_zoom_far))
        html = html.replace("{{ cluster_radius_far }}", str(settings.map_cluster_radius_far))
        html = html.replace("{{ cluster_zoom_medium }}", str(settings.map_cluster_zoom_medium))
        html = html.replace("{{ cluster_radius_medium }}", str(settings.map_cluster_radius_medium))
        html = html.replace("{{ cluster_radius_close }}", str(settings.map_cluster_radius_close))
        # Privacy settings
        html = html.replace("{{ redact_pii }}", str(redact_pii).lower())

        # Update fetch URLs to use hashed filenames
        html = html.replace("fetch('voters.geojson')", f"fetch('{voters_filename}')")
        if districts_filename:
            html = html.replace("fetch('districts.geojson')", f"fetch('{districts_filename}')")

        # Save HTML
        index_path = web_dir / html_filename
        index_path.write_text(html)
        logger.info(f"Saved {html_filename}: {index_path}")

        logger.info("Leaflet map web folder generated successfully")
        return str(index_path)

    else:
        # Legacy behavior: return embedded HTML string
        template_path = Path(__file__).parent / "templates" / "leaflet_map.html"
        if not template_path.exists():
            msg = f"Template file not found: {template_path}"
            raise FileNotFoundError(msg)

        template_content = template_path.read_text()

        # Replace template variables
        html = template_content.replace("{{ title }}", title)
        html = html.replace("{{ voters_geojson }}", json.dumps(voters_geojson))
        html = html.replace("{{ districts_geojson }}", json.dumps(districts_geojson))
        html = html.replace("{{ bounds }}", json.dumps(bounds))
        # Clustering configuration
        html = html.replace("{{ enable_clustering }}", str(settings.map_enable_clustering).lower())
        html = html.replace("{{ cluster_max_zoom }}", str(settings.map_cluster_max_zoom))
        html = html.replace(
            "{{ spiderfy_distance_multiplier }}", str(settings.map_spiderfy_distance_multiplier)
        )
        html = html.replace(
            "{{ show_coverage_on_hover }}", str(settings.map_cluster_show_coverage_on_hover).lower()
        )
        # Cluster zoom settings
        html = html.replace("{{ cluster_zoom_far }}", str(settings.map_cluster_zoom_far))
        html = html.replace("{{ cluster_radius_far }}", str(settings.map_cluster_radius_far))
        html = html.replace("{{ cluster_zoom_medium }}", str(settings.map_cluster_zoom_medium))
        html = html.replace("{{ cluster_radius_medium }}", str(settings.map_cluster_radius_medium))
        html = html.replace("{{ cluster_radius_close }}", str(settings.map_cluster_radius_close))
        # Privacy settings
        html = html.replace("{{ redact_pii }}", str(redact_pii).lower())

        logger.info("Leaflet map HTML generated successfully")
        return html


# ---------------------------------------------------------------------------
# Generalized district boundary import / comparison
# ---------------------------------------------------------------------------

# Common property-name patterns for auto-detection of district ID and name
_ID_CANDIDATES = [
    "DISTRICTID",
    "District",
    "DISTRICT",
    "district_id",
    "DistrictID",
    "ID",
    "id",
    "GEOID",
    "CODE",
    "DIST_NUM",
    "DIST_NO",
    "DIST",
    "Dist",
    "OBJECTID",
]
_NAME_CANDIDATES = [
    "NAME",
    "Name",
    "name",
    "NAMELSAD",
    "DISTRICT_NAME",
    "DistrictName",
    "LABEL",
    "Label",
    "DESCRIP",
    "Descrip",
    "SHORTLABEL",
    "ShortLabel",
]


def _read_boundary_features(file_path: Path) -> list[dict]:
    """Read district boundary features from GeoJSON, shapefile, or zip archive.

    Supports:
    - .geojson / .json files (GeoJSON FeatureCollection)
    - .shp files (ESRI Shapefile)
    - .zip files containing shapefiles (auto-detects .shp inside)

    All formats are normalized to a list of GeoJSON-style feature dicts with
    ``properties`` (dict) and ``geometry`` (dict) keys.

    Args:
        file_path: Path to the boundary file

    Returns:
        List of feature dicts, each with ``properties`` and ``geometry``.

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If the format is unsupported or contains no features
    """
    import geopandas as gpd

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()

    if suffix in (".geojson", ".json"):
        # Pure GeoJSON path – load directly for full fidelity
        with open(file_path) as f:
            geojson_data = json.load(f)

        if geojson_data.get("type") != "FeatureCollection":
            raise ValueError(
                f"Invalid GeoJSON: expected FeatureCollection, got {geojson_data.get('type')}"
            )
        features = geojson_data.get("features", [])
        if not features:
            raise ValueError("No features found in GeoJSON file")
        logger.info(f"Read {len(features)} features from GeoJSON")
        return features

    if suffix == ".zip":
        # Read shapefile inside the zip via geopandas
        gdf = _read_shapefile_zip(file_path)
    elif suffix == ".shp":
        logger.info(f"Reading shapefile: {file_path}")
        gdf = gpd.read_file(file_path)
    else:
        raise ValueError(
            f"Unsupported file format '{suffix}'. Supported: .geojson, .json, .shp, .zip"
        )

    if gdf.empty:
        raise ValueError("No features found in file")

    # Reproject to EPSG:4326 (WGS84) if needed
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        logger.info(f"Reprojecting from {gdf.crs} to EPSG:4326")
        gdf = gdf.to_crs(epsg=4326)

    # Convert to GeoJSON feature list
    features = json.loads(gdf.to_json()).get("features", [])
    logger.info(f"Read {len(features)} features from {suffix} file")
    return features


def _read_shapefile_zip(zip_path: Path):
    """Read the first .shp file found inside a zip archive.

    Args:
        zip_path: Path to the .zip file

    Returns:
        GeoDataFrame

    Raises:
        ValueError: If no .shp file is found in the archive
    """
    import geopandas as gpd
    import zipfile

    logger.info(f"Scanning zip archive: {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        shp_names = [n for n in zf.namelist() if n.lower().endswith(".shp")]

    if not shp_names:
        raise ValueError(f"No .shp file found inside {zip_path.name}")

    # Use the first .shp found (most zip archives contain exactly one)
    shp_name = shp_names[0]
    logger.info(f"Found shapefile in zip: {shp_name}")

    # geopandas can read directly from zip:// URI
    uri = f"zip://{zip_path}!{shp_name}"
    return gpd.read_file(uri)


def _log_detected_properties(features: list[dict]) -> None:
    """Log the property keys found in the first feature for debugging."""
    if features:
        props = features[0].get("properties", {})
        logger.info(f"Available properties: {list(props.keys())}")
        # Log first feature values for easier debugging
        for k, v in props.items():
            logger.debug(f"  {k} = {v!r}")


def import_district_boundaries(
    session: Session,
    file_path: Path,
    district_type: str,
    clear_existing: bool = False,
    id_property: str | None = None,
    name_property: str | None = None,
) -> dict[str, int]:
    """Import district boundaries from GeoJSON, shapefile, or zip for any district type.

    Supports .geojson, .json, .shp, and .zip (containing shapefiles).
    Shapefiles are automatically reprojected to EPSG:4326 if needed.

    Args:
        session: Database session
        file_path: Path to boundary file (.geojson, .shp, or .zip)
        district_type: Key from DISTRICT_TYPES (e.g., "congressional")
        clear_existing: Delete existing boundaries for this type first
        id_property: Property key for the district ID (auto-detected if omitted)
        name_property: Property key for the district name (auto-detected if omitted)

    Returns:
        Dictionary with statistics: total, success, failed, skipped
    """
    if district_type not in DISTRICT_TYPES:
        raise ValueError(
            f"Unknown district type '{district_type}'. "
            f"Valid types: {', '.join(sorted(DISTRICT_TYPES))}"
        )

    logger.info(f"Importing {district_type} boundaries from {file_path}")

    # Clear existing boundaries for this district type if requested
    if clear_existing:
        count = (
            session.query(DistrictBoundary)
            .filter(DistrictBoundary.district_type == district_type)
            .count()
        )
        if count > 0:
            logger.info(f"Clearing {count} existing {district_type} boundaries...")
            session.query(DistrictBoundary).filter(
                DistrictBoundary.district_type == district_type
            ).delete()
            session.commit()

    # Read features from any supported format
    features = _read_boundary_features(file_path)
    _log_detected_properties(features)

    logger.info(f"Found {len(features)} features to import")

    stats: dict[str, int] = {"total": len(features), "success": 0, "failed": 0, "skipped": 0}

    # Prefetch existing district IDs to avoid N+1 queries
    existing_ids_stmt = (
        session.query(DistrictBoundary.district_id)
        .filter(DistrictBoundary.district_type == district_type)
        .all()
    )
    existing_district_ids = {row[0] for row in existing_ids_stmt}
    logger.debug(
        f"Found {len(existing_district_ids)} existing {district_type} districts in database"
    )

    for idx, feature in enumerate(features, 1):
        try:
            props = feature.get("properties", {})
            geometry = feature.get("geometry")

            if not geometry:
                logger.warning(f"Feature {idx}: Missing geometry, skipping")
                stats["skipped"] += 1
                continue

            # Resolve district_id
            did = None
            if id_property:
                did = props.get(id_property)
            else:
                for cand in _ID_CANDIDATES:
                    did = props.get(cand)
                    if did is not None:
                        break

            # Resolve name
            dname = None
            if name_property:
                dname = props.get(name_property)
            else:
                for cand in _NAME_CANDIDATES:
                    dname = props.get(cand)
                    if dname is not None:
                        break

            if did is None:
                logger.warning(f"Feature {idx}: Could not find district ID property, skipping")
                stats["skipped"] += 1
                continue

            did = str(did).strip()
            if not dname:
                dname = f"{district_type} {did}"

            # Check for duplicates using prefetched set
            if did in existing_district_ids:
                logger.debug(f"District {district_type}/{did} already exists, skipping")
                stats["skipped"] += 1
                continue

            # Convert GeoJSON geometry to PostGIS
            shapely_geom = shape(geometry)
            wkt = shapely_geom.wkt
            geom = WKTElement(wkt, srid=4326)

            # Collect optional representative metadata
            rep_name = props.get("REPNAME1") or props.get("Commissioner") or props.get("rep_name")
            party = props.get("PARTY1") or props.get("Party") or props.get("party")
            email = props.get("Email") or props.get("E_Mail") or props.get("email")
            website = (
                props.get("DISTRICTURL1") or props.get("District_URL") or props.get("website_url")
            )
            photo = props.get("Photo") or props.get("Photo_URL") or props.get("photo_url")

            # Store remaining properties as extra
            known_keys = (
                {
                    id_property,
                    name_property,
                    "REPNAME1",
                    "Commissioner",
                    "rep_name",
                    "PARTY1",
                    "Party",
                    "party",
                    "Email",
                    "E_Mail",
                    "email",
                    "DISTRICTURL1",
                    "District_URL",
                    "website_url",
                    "Photo",
                    "Photo_URL",
                    "photo_url",
                }
                | set(_ID_CANDIDATES)
                | set(_NAME_CANDIDATES)
            )
            extra = {k: v for k, v in props.items() if k not in known_keys}

            boundary = DistrictBoundary(
                district_type=district_type,
                district_id=did,
                name=str(dname),
                rep_name=rep_name,
                party=party,
                email=email,
                website_url=website,
                photo_url=photo,
                extra_properties=extra if extra else None,
                geom=geom,
            )
            session.add(boundary)
            stats["success"] += 1

            if stats["success"] % 100 == 0:
                logger.info(f"Progress: {stats['success']}/{len(features)} boundaries imported...")

        except Exception as e:
            logger.warning(f"Feature {idx}: Failed to import - {e}")
            stats["failed"] += 1

    session.commit()

    logger.info(
        f"Import complete: {stats['success']} imported, "
        f"{stats['skipped']} skipped, {stats['failed']} failed"
    )
    return stats


def compare_all_districts(
    session: Session,
    district_types: list[str] | None = None,
    limit: int | None = None,
    save_to_db: bool = False,
) -> dict[str, dict]:
    """Compare voter registrations against spatial boundaries for multiple district types.

    For each requested district type that has boundaries in the database, runs a
    PostGIS spatial join to determine which boundary polygon contains each
    voter's geocoded point, then compares against the voter-roll value.

    Args:
        session: Database session
        district_types: List of district-type keys to compare.
                        If None, compares all types that have boundaries.
        limit: Optional limit on voters to process (for testing)
        save_to_db: If True, persist results to voter_district_assignments

    Returns:
        Dict keyed by district_type with per-type stats:
        {
            "county_commission": {
                "total": int, "matched": int, "mismatched": int,
                "no_district": int, "no_registered": int
            },
            ...
        }
    """
    from datetime import datetime

    # Determine which types to compare based on available boundaries
    available_stmt = session.query(DistrictBoundary.district_type).distinct().all()
    available_types = {row[0] for row in available_stmt}

    if not available_types:
        logger.warning("No district boundaries found in database")
        return {}

    # Validate that available types are recognized
    valid_available_types = available_types & set(DISTRICT_TYPES.keys())
    invalid_types = available_types - set(DISTRICT_TYPES.keys())

    if invalid_types:
        logger.warning(
            f"Found {len(invalid_types)} unknown district type(s) in database: "
            f"{', '.join(sorted(invalid_types))}. These will be skipped. "
            f"Valid types: {', '.join(sorted(DISTRICT_TYPES.keys()))}"
        )

    # Use validated types instead of raw available_types
    available_types = valid_available_types

    if district_types:
        types_to_compare = [t for t in district_types if t in available_types]
        missing = set(district_types) - available_types
        if missing:
            logger.warning(f"No boundaries found for: {', '.join(missing)}")
    else:
        types_to_compare = sorted(available_types)

    if not types_to_compare:
        logger.warning("No matching district types to compare")
        return {}

    logger.info(
        f"Comparing {len(types_to_compare)} district type(s): {', '.join(types_to_compare)}"
    )

    results: dict[str, dict] = {}
    comparison_time = datetime.now()

    for dtype in types_to_compare:
        voter_column = DISTRICT_TYPES[dtype]
        logger.info(f"Comparing district type '{dtype}' (voter column: {voter_column})...")

        # Spatial join query with DISTINCT ON to handle overlapping boundaries
        query_sql = f"""
            SELECT DISTINCT ON (v.voter_registration_number)
                v.voter_registration_number,
                v.{voter_column} AS registered_value,
                d.district_id AS spatial_district_id,
                d.name AS spatial_district_name
            FROM voters v
            LEFT JOIN district_boundaries d
                ON d.district_type = :district_type
                AND ST_Within(v.geom, d.geom)
            WHERE v.geom IS NOT NULL
            ORDER BY v.voter_registration_number, d.district_id ASC
        """
        if limit:
            query_sql += " LIMIT :limit_val"
            rows = session.execute(
                text(query_sql), {"district_type": dtype, "limit_val": limit}
            ).fetchall()
        else:
            rows = session.execute(text(query_sql), {"district_type": dtype}).fetchall()

        stats = {
            "total": len(rows),
            "matched": 0,
            "mismatched": 0,
            "no_district": 0,
            "no_registered": 0,
        }

        assignments: list[dict] = []

        for row in rows:
            voter_id = row[0]
            registered = row[1]
            spatial_id = row[2]
            spatial_name = row[3]

            if not spatial_id:
                stats["no_district"] += 1
                if save_to_db:
                    assignments.append(
                        {
                            "voter_id": voter_id,
                            "district_type": dtype,
                            "registered_value": registered,
                            "spatial_district_id": None,
                            "spatial_district_name": None,
                            "is_mismatch": None,
                            "compared_at": comparison_time,
                        }
                    )
                continue

            if not registered:
                stats["no_registered"] += 1
                if save_to_db:
                    assignments.append(
                        {
                            "voter_id": voter_id,
                            "district_type": dtype,
                            "registered_value": None,
                            "spatial_district_id": spatial_id,
                            "spatial_district_name": spatial_name,
                            "is_mismatch": None,
                            "compared_at": comparison_time,
                        }
                    )
                continue

            # Normalize for comparison: strip "District" prefix, whitespace
            reg_norm = registered.replace("District", "").replace("district", "").strip()
            spat_norm = spatial_id.strip()

            is_match = reg_norm == spat_norm
            if is_match:
                stats["matched"] += 1
            else:
                stats["mismatched"] += 1

            if save_to_db:
                assignments.append(
                    {
                        "voter_id": voter_id,
                        "district_type": dtype,
                        "registered_value": registered,
                        "spatial_district_id": spatial_id,
                        "spatial_district_name": spatial_name,
                        "is_mismatch": not is_match,
                        "compared_at": comparison_time,
                    }
                )

        results[dtype] = stats

        logger.info(
            f"  {dtype}: {stats['matched']} matched, "
            f"{stats['mismatched']} mismatched, "
            f"{stats['no_district']} no boundary, "
            f"{stats['no_registered']} no registration value"
        )

        # Persist results if requested
        if save_to_db and assignments:
            _save_district_assignments(session, dtype, assignments)

    # Update legacy district_mismatch field after all districts are compared
    if save_to_db:
        _update_legacy_mismatch_field(session)

    return results


def _save_district_assignments(
    session: Session,
    district_type: str,
    assignments: list[dict],
) -> None:
    """Upsert voter district assignment records for a single district type.

    Args:
        session: Database session
        district_type: The district type being saved
        assignments: List of assignment dicts
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    logger.info(f"Saving {len(assignments)} assignments for {district_type}...")

    batch_size = 1000
    for i in range(0, len(assignments), batch_size):
        batch = assignments[i : i + batch_size]
        stmt = pg_insert(VoterDistrictAssignment).values(batch)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_voter_district_type",
            set_={
                "registered_value": stmt.excluded.registered_value,
                "spatial_district_id": stmt.excluded.spatial_district_id,
                "spatial_district_name": stmt.excluded.spatial_district_name,
                "is_mismatch": stmt.excluded.is_mismatch,
                "compared_at": stmt.excluded.compared_at,
            },
        )
        session.execute(stmt)

    session.commit()
    logger.info(f"Saved {len(assignments)} assignments for {district_type}")


def _update_legacy_mismatch_field(session: Session) -> int:
    """Update Voter.district_mismatch from VoterDistrictAssignment.

    Sets district_mismatch = True if voter has ANY mismatch across ANY district type.
    This maintains backward compatibility with existing QGIS projects and queries.

    Returns:
        Number of voters updated
    """
    from sqlalchemy import text

    logger.info("Updating legacy Voter.district_mismatch field from VoterDistrictAssignment")

    # Update using SQL for efficiency
    update_sql = """
        UPDATE voters
        SET district_mismatch = subquery.has_mismatch,
            district_compared_at = NOW()
        FROM (
            SELECT
                voter_id,
                BOOL_OR(is_mismatch) as has_mismatch
            FROM voter_district_assignments
            GROUP BY voter_id
        ) as subquery
        WHERE voters.voter_registration_number = subquery.voter_id
    """

    result = session.execute(text(update_sql))
    session.commit()

    updated_count = result.rowcount
    logger.info(f"Updated district_mismatch for {updated_count} voters")

    return updated_count


def get_district_status(session: Session) -> dict[str, dict]:
    """Return summary statistics for imported boundaries and comparison results.

    Returns:
        Dict keyed by district_type, each containing:
        {
            "boundaries": int,         # number of imported boundaries
            "voters_compared": int,     # voters with comparison results
            "matched": int,
            "mismatched": int,
            "no_district": int,
            "no_registered": int,
        }
    """
    # Count boundaries per type
    boundary_counts = (
        session.query(
            DistrictBoundary.district_type,
            func.count().label("cnt"),
        )
        .group_by(DistrictBoundary.district_type)
        .all()
    )
    boundary_map = {row[0]: row[1] for row in boundary_counts}

    # Count assignment results per type
    assignment_stats = (
        session.query(
            VoterDistrictAssignment.district_type,
            func.count().label("total"),
            func.sum(case((VoterDistrictAssignment.is_mismatch == False, 1), else_=0)).label(  # noqa: E712
                "matched"
            ),
            func.sum(case((VoterDistrictAssignment.is_mismatch == True, 1), else_=0)).label(  # noqa: E712
                "mismatched"
            ),
            func.sum(
                case(
                    (
                        VoterDistrictAssignment.is_mismatch.is_(None)
                        & VoterDistrictAssignment.spatial_district_id.is_(None),
                        1,
                    ),
                    else_=0,
                )
            ).label("no_district"),
            func.sum(
                case(
                    (
                        VoterDistrictAssignment.is_mismatch.is_(None)
                        & VoterDistrictAssignment.spatial_district_id.isnot(None),
                        1,
                    ),
                    else_=0,
                )
            ).label("no_registered"),
        )
        .group_by(VoterDistrictAssignment.district_type)
        .all()
    )
    assignment_map = {
        row[0]: {
            "voters_compared": row[1],
            "matched": row[2] or 0,
            "mismatched": row[3] or 0,
            "no_district": row[4] or 0,
            "no_registered": row[5] or 0,
        }
        for row in assignment_stats
    }

    # Merge
    all_types = sorted(set(boundary_map.keys()) | set(assignment_map.keys()))
    result = {}
    for dtype in all_types:
        result[dtype] = {
            "boundaries": boundary_map.get(dtype, 0),
            **assignment_map.get(
                dtype,
                {
                    "voters_compared": 0,
                    "matched": 0,
                    "mismatched": 0,
                    "no_district": 0,
                    "no_registered": 0,
                },
            ),
        }

    return result
