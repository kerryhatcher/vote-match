"""Geocoding functionality using US Census Batch Geocoder API."""

import csv
from dataclasses import dataclass
from io import BytesIO, StringIO

import httpx
from loguru import logger

from vote_match.config import Settings
from vote_match.models import Voter


@dataclass
class GeocodeResult:
    """Result from Census geocoder for a single address."""

    registration_number: str  # Voter registration number (matches back to voter)
    status: str  # 'matched', 'no_match', or 'failed'
    match_type: str | None  # e.g., 'Exact', 'Non_Exact'
    matched_address: str | None  # Standardized address from Census
    longitude: float | None
    latitude: float | None
    tigerline_id: str | None
    tigerline_side: str | None
    state_fips: str | None
    county_fips: str | None
    tract: str | None
    block: str | None


def build_batch_csv(voters: list[Voter]) -> str:
    """
    Construct CSV string for Census Batch Geocoder from voter records.

    The Census API expects a CSV with NO header and the format:
    {unique_id},{street_address},{city},{state},{zip}

    Args:
        voters: List of Voter objects to geocode.

    Returns:
        CSV string (no header) ready for submission to Census API.
    """
    output = StringIO()
    writer = csv.writer(output)

    skipped = 0
    for voter in voters:
        # Build street address from components
        street = voter.build_street_address()

        # Get city
        city = voter.residence_city

        # Get zipcode
        zipcode = voter.residence_zipcode

        # Skip voters with missing required fields
        if not street or not city or not zipcode:
            logger.debug(
                "Skipping voter {} due to missing address fields",
                voter.voter_registration_number,
            )
            skipped += 1
            continue

        # Use "GA" as default state (could be from settings)
        state = "GA"

        # Write row: ID, street, city, state, zip
        writer.writerow([
            voter.voter_registration_number,
            street,
            city,
            state,
            zipcode,
        ])

    if skipped > 0:
        logger.info("Skipped {} voters with incomplete addresses", skipped)

    csv_content = output.getvalue()
    output.close()

    logger.debug("Built batch CSV with {} records", len(voters) - skipped)
    return csv_content


def submit_batch(csv_content: str, settings: Settings) -> str:
    """
    Submit batch geocoding request to Census API.

    Args:
        csv_content: CSV string to submit (no header).
        settings: Application settings with API configuration.

    Returns:
        Response CSV string from Census API.

    Raises:
        httpx.HTTPError: On HTTP errors.
        httpx.TimeoutException: On request timeout.
    """
    url = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"

    # Count records in batch
    batch_size = csv_content.count("\n") if csv_content else 0
    logger.info(
        "Submitting batch of {} records to Census API (timeout: {}s)",
        batch_size,
        settings.census_timeout,
    )
    logger.debug("Benchmark: {}, Vintage: {}", settings.census_benchmark, settings.census_vintage)

    # Prepare multipart form data with BytesIO
    files = {
        "addressFile": ("batch.csv", BytesIO(csv_content.encode("utf-8")), "text/csv"),
    }
    data = {
        "benchmark": settings.census_benchmark,
        "vintage": settings.census_vintage,
    }

    try:
        # Submit request with timeout
        with httpx.Client(timeout=settings.census_timeout) as client:
            response = client.post(url, files=files, data=data)
            response.raise_for_status()

        logger.info("Received response from Census API ({} bytes)", len(response.text))
        return response.text

    except httpx.TimeoutException as e:
        logger.error("Census API request timed out after {}s", settings.census_timeout)
        raise

    except httpx.HTTPError as e:
        logger.error("Census API HTTP error: {}", str(e))
        raise


def parse_response(response_text: str) -> list[GeocodeResult]:
    """
    Parse Census geocoder response CSV into GeocodeResult objects.

    The Census API returns CSV with format:
    {id},{input_address},{match_indicator},{match_type},{matched_address},
    {lon/lat_coords},{tigerline_id},{side},{state_fips},{county_fips},{tract},{block}

    Match indicators:
    - "Match" - Address was geocoded
    - "No_Match" - Address could not be geocoded
    - "Tie" - Multiple matches found (rare)

    Args:
        response_text: CSV response text from Census API.

    Returns:
        List of GeocodeResult objects.
    """
    results = []
    reader = csv.reader(StringIO(response_text))

    for row in reader:
        if len(row) < 3:
            logger.warning("Skipping malformed response row: {}", row)
            continue

        # Extract fields from response
        registration_number = row[0].strip()
        match_indicator = row[2].strip() if len(row) > 2 else ""

        # Map match indicator to status
        if match_indicator == "Match":
            status = "matched"
        elif match_indicator == "No_Match":
            status = "no_match"
        elif match_indicator == "Tie":
            status = "matched"  # Treat tie as matched (uses first match)
        else:
            logger.warning("Unknown match indicator '{}' for voter {}", match_indicator, registration_number)
            status = "failed"

        # Extract match details (only present for successful matches)
        match_type = None
        matched_address = None
        longitude = None
        latitude = None
        tigerline_id = None
        tigerline_side = None
        state_fips = None
        county_fips = None
        tract = None
        block = None

        if status == "matched" and len(row) >= 12:
            # Match type (exact, non-exact)
            match_type = row[3].strip() if row[3].strip() else None

            # Matched address
            matched_address = row[4].strip() if row[4].strip() else None

            # Coordinates (format: "(-lon, lat)" or "(lon, lat)")
            coords_str = row[5].strip()
            if coords_str:
                # Parse coordinates from "(lon, lat)" format
                coords_str = coords_str.strip("()")
                try:
                    parts = [p.strip() for p in coords_str.split(",")]
                    if len(parts) == 2:
                        longitude = float(parts[0])
                        latitude = float(parts[1])
                except (ValueError, IndexError) as e:
                    logger.warning("Failed to parse coordinates '{}' for voter {}: {}", coords_str, registration_number, str(e))

            # TIGER/Line fields
            tigerline_id = row[6].strip() if row[6].strip() else None
            tigerline_side = row[7].strip() if row[7].strip() else None
            state_fips = row[8].strip() if row[8].strip() else None
            county_fips = row[9].strip() if row[9].strip() else None
            tract = row[10].strip() if row[10].strip() else None
            block = row[11].strip() if row[11].strip() else None

        result = GeocodeResult(
            registration_number=registration_number,
            status=status,
            match_type=match_type,
            matched_address=matched_address,
            longitude=longitude,
            latitude=latitude,
            tigerline_id=tigerline_id,
            tigerline_side=tigerline_side,
            state_fips=state_fips,
            county_fips=county_fips,
            tract=tract,
            block=block,
        )

        results.append(result)
        logger.debug("Parsed result for voter {}: {}", registration_number, status)

    logger.info("Parsed {} results from Census response", len(results))
    return results
