"""Census Geocoder service implementation."""

import csv
from io import BytesIO, StringIO
from typing import Any

import httpx
from loguru import logger

from vote_match.config import Settings
from vote_match.models import Voter

from ..base import (
    GeocodeQuality,
    GeocodeService,
    GeocodeServiceType,
    StandardGeocodeResult,
)
from ..registry import GeocodeServiceRegistry


@GeocodeServiceRegistry.register
class CensusGeocoder(GeocodeService):
    """US Census Batch Geocoder API implementation."""

    def __init__(self, config: Settings):
        """Initialize Census geocoder with configuration.

        Args:
            config: Application settings containing census configuration
        """
        super().__init__(config)
        self.census_config = config.geocode_services.census

    @property
    def service_name(self) -> str:
        """Unique identifier for this service."""
        return "census"

    @property
    def service_type(self) -> GeocodeServiceType:
        """Census supports batch processing."""
        return GeocodeServiceType.BATCH

    @property
    def requires_api_key(self) -> bool:
        """Census geocoder is free and requires no API key."""
        return False

    def prepare_addresses(self, voters: list[Voter]) -> str:
        """Format voter addresses for Census batch API.

        The Census API expects CSV with NO header:
        {unique_id},{street_address},{city},{state},{zip}

        Args:
            voters: List of Voter model instances

        Returns:
            CSV string (no header) ready for submission
        """
        output = StringIO()
        writer = csv.writer(output)

        skipped = 0
        for voter in voters:
            # Build street address from components
            street = voter.build_street_address()
            city = voter.residence_city
            zipcode = voter.residence_zipcode

            # Skip voters with missing required fields
            if not street or not city or not zipcode:
                logger.debug(
                    f"Skipping voter {voter.voter_registration_number} "
                    f"due to missing address fields"
                )
                skipped += 1
                continue

            # Use default state from config
            state = self.config.default_state

            # Write row: ID, street, city, state, zip
            writer.writerow(
                [
                    voter.voter_registration_number,
                    street,
                    city,
                    state,
                    zipcode,
                ]
            )

        if skipped > 0:
            logger.info(f"Skipped {skipped} voters with incomplete addresses")

        csv_content = output.getvalue()
        output.close()

        logger.debug(f"Built batch CSV with {len(voters) - skipped} records")
        return csv_content

    def submit_request(self, prepared_data: str) -> str:
        """Submit batch geocoding request to Census API.

        Args:
            prepared_data: CSV string from prepare_addresses()

        Returns:
            Response CSV string from Census API

        Raises:
            httpx.HTTPError: On HTTP errors
            httpx.TimeoutException: On request timeout
        """
        url = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"

        # Count records in batch
        batch_size = prepared_data.count("\n") if prepared_data else 0
        logger.info(
            f"Submitting batch of {batch_size} records to Census API "
            f"(timeout: {self.census_config.timeout}s)"
        )
        logger.debug(
            f"Benchmark: {self.census_config.benchmark}, "
            f"Vintage: {self.census_config.vintage}"
        )

        # Prepare multipart form data
        files = {
            "addressFile": (
                "batch.csv",
                BytesIO(prepared_data.encode("utf-8")),
                "text/csv",
            ),
        }
        data = {
            "benchmark": self.census_config.benchmark,
            "vintage": self.census_config.vintage,
        }

        try:
            # Submit request with timeout
            with httpx.Client(timeout=self.census_config.timeout) as client:
                response = client.post(url, files=files, data=data)
                response.raise_for_status()

            logger.info(f"Received response from Census API ({len(response.text)} bytes)")
            return response.text

        except httpx.TimeoutException:
            logger.error(f"Census API request timed out after {self.census_config.timeout}s")
            raise

        except httpx.HTTPError as e:
            logger.error(f"Census API HTTP error: {e}")
            raise

    def parse_response(
        self, response: str, voters: list[Voter]
    ) -> list[StandardGeocodeResult]:
        """Parse Census API response into standardized results.

        The Census API returns CSV with format:
        {id},{input_address},{match_indicator},{match_type},{matched_address},
        {lon/lat_coords},{tigerline_id},{side},{state_fips},{county_fips},{tract},{block}

        Match indicators:
        - "Match" - Address was geocoded
        - "No_Match" - Address could not be geocoded
        - "Tie" - Multiple matches found (uses first match)

        Args:
            response: Raw CSV response from Census API
            voters: Original list of voters (for matching results)

        Returns:
            List of StandardGeocodeResult objects
        """
        results = []
        reader = csv.reader(StringIO(response))

        # Create lookup map for voters by registration number
        voter_map = {v.voter_registration_number: v for v in voters}

        for row in reader:
            if len(row) < 3:
                logger.warning(f"Skipping malformed response row: {row}")
                continue

            # Extract basic fields
            registration_number = row[0].strip()
            match_indicator = row[2].strip() if len(row) > 2 else ""

            # Get voter ID for this result
            voter = voter_map.get(registration_number)
            if not voter:
                logger.warning(f"No voter found for registration number: {registration_number}")
                continue

            # Map match indicator to quality status
            if match_indicator == "Match":
                # Determine quality based on match type
                match_type = row[3].strip() if len(row) > 3 else ""
                if match_type.lower() == "exact":
                    status = GeocodeQuality.EXACT
                else:
                    status = GeocodeQuality.INTERPOLATED
            elif match_indicator == "No_Match":
                status = GeocodeQuality.NO_MATCH
            elif match_indicator == "Tie":
                # Treat tie as interpolated (uses first match)
                status = GeocodeQuality.INTERPOLATED
            else:
                logger.warning(
                    f"Unknown match indicator '{match_indicator}' "
                    f"for voter {registration_number}"
                )
                status = GeocodeQuality.FAILED

            # Extract match details (only present for successful matches)
            longitude = None
            latitude = None
            matched_address = None
            match_confidence = None

            # Build raw response dictionary
            raw_response: dict[str, Any] = {
                "match_indicator": match_indicator,
                "input_address": row[1].strip() if len(row) > 1 else None,
            }

            if status in [GeocodeQuality.EXACT, GeocodeQuality.INTERPOLATED] and len(row) >= 12:
                # Match type
                match_type_value = row[3].strip() if row[3].strip() else None
                raw_response["match_type"] = match_type_value

                # Matched address
                matched_address = row[4].strip() if row[4].strip() else None

                # Coordinates (format: "(-lon, lat)" or "(lon, lat)")
                coords_str = row[5].strip()
                if coords_str:
                    coords_str = coords_str.strip("()")
                    try:
                        parts = [p.strip() for p in coords_str.split(",")]
                        if len(parts) == 2:
                            longitude = float(parts[0])
                            latitude = float(parts[1])
                    except (ValueError, IndexError) as e:
                        logger.warning(
                            f"Failed to parse coordinates '{coords_str}' "
                            f"for voter {registration_number}: {e}"
                        )

                # TIGER/Line fields (stored in raw_response)
                raw_response.update(
                    {
                        "tigerline_id": row[6].strip() if row[6].strip() else None,
                        "tigerline_side": row[7].strip() if row[7].strip() else None,
                        "state_fips": row[8].strip() if row[8].strip() else None,
                        "county_fips": row[9].strip() if row[9].strip() else None,
                        "tract": row[10].strip() if row[10].strip() else None,
                        "block": row[11].strip() if row[11].strip() else None,
                    }
                )

                # Census doesn't provide confidence scores, so we'll estimate based on match type
                if match_type_value and match_type_value.lower() == "exact":
                    match_confidence = 1.0
                else:
                    match_confidence = 0.85  # Non-exact matches

            result = StandardGeocodeResult(
                voter_id=registration_number,
                service_name=self.service_name,
                status=status,
                longitude=longitude,
                latitude=latitude,
                matched_address=matched_address,
                match_confidence=match_confidence,
                raw_response=raw_response,
                error_message=None,
            )

            results.append(result)
            logger.debug(f"Parsed result for voter {registration_number}: {status.value}")

        logger.info(f"Parsed {len(results)} results from Census response")
        return results
