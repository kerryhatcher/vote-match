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
