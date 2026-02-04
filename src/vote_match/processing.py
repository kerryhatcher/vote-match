"""Processing functions for geocoding voter records."""

from typing import Optional

from geoalchemy2 import WKTElement
from loguru import logger
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from vote_match.config import Settings
from vote_match.geocoder import GeocodeResult, build_batch_csv, parse_response, submit_batch
from vote_match.geocoding.base import GeocodeService, StandardGeocodeResult
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
