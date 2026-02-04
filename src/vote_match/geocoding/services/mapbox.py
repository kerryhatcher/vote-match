"""Mapbox Geocoding API service implementation."""

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
class MapboxGeocoder(GeocodeService):
    """Mapbox Geocoding API v6 implementation (batch support, global coverage)."""

    def __init__(self, config: Settings):
        """Initialize Mapbox geocoder with configuration.

        Args:
            config: Application settings containing mapbox configuration
        """
        super().__init__(config)
        self.mapbox_config = config.geocode_services.mapbox

    @property
    def service_name(self) -> str:
        """Unique identifier for this service."""
        return "mapbox"

    @property
    def service_type(self) -> GeocodeServiceType:
        """Mapbox v6 supports batch processing."""
        return GeocodeServiceType.BATCH

    @property
    def requires_api_key(self) -> bool:
        """Mapbox requires an access token (API key)."""
        return True

    def prepare_addresses(self, voters: list[Voter]) -> list[dict[str, str]]:
        """Format voter addresses for Mapbox batch API.

        The Mapbox v6 API expects a JSON array of query objects:
        [{"q": "123 Main St, City, ST ZIP"}, ...]

        Args:
            voters: List of Voter model instances

        Returns:
            List of query dictionaries ready for submission
        """
        queries = []
        skipped = 0

        for voter in voters:
            # Build street address from components
            street = voter.build_street_address()
            city = voter.residence_city
            zipcode = voter.residence_zipcode

            # Skip voters with missing required fields
            if not street or not city:
                logger.debug(
                    f"Skipping voter {voter.voter_registration_number} "
                    f"due to missing address fields"
                )
                skipped += 1
                continue

            # Use default state from config
            state = self.config.default_state

            # Format address as single string: "street, city, state zip"
            address_parts = [street, city]
            if zipcode:
                address_parts.append(f"{state} {zipcode}")
            else:
                address_parts.append(state)

            address = ", ".join(address_parts)
            queries.append({"q": address})

        if skipped > 0:
            logger.info(f"Skipped {skipped} voters with incomplete addresses")

        logger.debug(f"Prepared {len(queries)} queries for Mapbox batch")
        return queries

    def submit_request(self, prepared_data: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Submit batch geocoding request to Mapbox v6 API.

        Args:
            prepared_data: List of query dicts from prepare_addresses()

        Returns:
            List of GeoJSON Feature objects (one per query)

        Raises:
            httpx.HTTPError: On HTTP errors
            httpx.TimeoutException: On request timeout
            ValueError: If API key is not configured
        """
        if not self.mapbox_config.api_key:
            raise ValueError(
                "Mapbox API key not configured. "
                "Set VOTE_MATCH_GEOCODE_SERVICES__MAPBOX__API_KEY environment variable."
            )

        url = f"{self.mapbox_config.base_url}/geocoding/{self.mapbox_config.api_version}/forward"

        batch_size = len(prepared_data)
        logger.info(
            f"Submitting batch of {batch_size} queries to Mapbox API "
            f"(timeout: {self.mapbox_config.timeout}s)"
        )

        # Build query parameters
        params = {
            "access_token": self.mapbox_config.api_key,
            "country": self.mapbox_config.country,
            "limit": 1,  # Only return best match
            "types": "address",  # Prefer address-level results
        }

        try:
            # Submit request with timeout
            with httpx.Client(timeout=self.mapbox_config.timeout) as client:
                response = client.post(
                    url,
                    params=params,
                    headers={"Content-Type": "application/json"},
                    json=prepared_data,
                )
                response.raise_for_status()

            logger.info(f"Received response from Mapbox API ({len(response.text)} bytes)")
            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code in [401, 403]:
                logger.error("Mapbox API authentication failed - check access token")
            elif e.response.status_code == 429:
                logger.error("Mapbox API rate limit exceeded")
            else:
                logger.error(f"Mapbox API HTTP error: {e}")
            raise

        except httpx.TimeoutException:
            logger.error(f"Mapbox API request timed out after {self.mapbox_config.timeout}s")
            raise

        except httpx.HTTPError as e:
            logger.error(f"Mapbox API error: {e}")
            raise

    def parse_response(
        self, response: list[dict[str, Any]], voters: list[Voter]
    ) -> list[StandardGeocodeResult]:
        """Parse Mapbox API response into standardized results.

        The Mapbox v6 API returns an array of GeoJSON Feature objects:
        [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "full_address": "string",
                    "place_name": "string",
                    "match_code": {"confidence": "high|medium|low"},
                    ...
                }
            },
            ...
        ]

        Args:
            response: List of GeoJSON Feature objects from Mapbox API
            voters: Original list of voters (for matching results)

        Returns:
            List of StandardGeocodeResult objects
        """
        results = []

        if len(response) != len(voters):
            logger.warning(
                f"Response count ({len(response)}) does not match voter count ({len(voters)})"
            )

        # Process each feature (order should match input order)
        for i, feature in enumerate(response):
            if i >= len(voters):
                logger.warning(f"Extra feature at index {i} with no matching voter")
                break

            voter = voters[i]
            registration_number = voter.voter_registration_number

            # Check if feature has geometry (indicates a match)
            geometry = feature.get("geometry")
            properties = feature.get("properties", {})

            # Handle case where no match was found
            if not geometry or not geometry.get("coordinates"):
                result = StandardGeocodeResult(
                    voter_id=registration_number,
                    service_name=self.service_name,
                    status=GeocodeQuality.NO_MATCH,
                    longitude=None,
                    latitude=None,
                    matched_address=None,
                    match_confidence=None,
                    raw_response={"feature": feature},
                    error_message=None,
                )
                results.append(result)
                logger.debug(f"No match found for voter {registration_number}")
                continue

            # Extract coordinates (GeoJSON format: [lon, lat])
            coordinates = geometry["coordinates"]
            longitude = coordinates[0]
            latitude = coordinates[1]

            # Extract matched address (prefer full_address, fallback to place_name)
            matched_address = properties.get("full_address") or properties.get("place_name")

            # Extract confidence from match_code
            match_code = properties.get("match_code", {})
            confidence_level = match_code.get("confidence", "").lower()

            # Map confidence level to quality status and score
            if confidence_level == "high":
                status = GeocodeQuality.EXACT
                confidence_score = 0.9
            elif confidence_level == "medium":
                status = GeocodeQuality.INTERPOLATED
                confidence_score = 0.7
            elif confidence_level == "low":
                status = GeocodeQuality.APPROXIMATE
                confidence_score = 0.5
            else:
                # Unknown confidence level
                logger.warning(
                    f"Unknown confidence level '{confidence_level}' for voter {registration_number}"
                )
                status = GeocodeQuality.APPROXIMATE
                confidence_score = 0.5

            # Create standardized result
            result = StandardGeocodeResult(
                voter_id=registration_number,
                service_name=self.service_name,
                status=status,
                longitude=longitude,
                latitude=latitude,
                matched_address=matched_address,
                match_confidence=confidence_score,
                raw_response={
                    "feature": feature,
                    "confidence_level": confidence_level,
                },
                error_message=None,
            )

            results.append(result)
            logger.debug(f"Parsed result for voter {registration_number}: {status.value}")

        logger.info(f"Parsed {len(results)} results from Mapbox response")
        return results
