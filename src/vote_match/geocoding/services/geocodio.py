"""Geocodio API service implementation."""

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
class GeocodioGeocoder(GeocodeService):
    """Geocodio API implementation (US/Canada only, batch support)."""

    def __init__(self, config: Settings):
        """Initialize Geocodio geocoder with configuration.

        Args:
            config: Application settings containing geocodio configuration
        """
        super().__init__(config)
        self.geocodio_config = config.geocode_services.geocodio

    @property
    def service_name(self) -> str:
        """Unique identifier for this service."""
        return "geocodio"

    @property
    def service_type(self) -> GeocodeServiceType:
        """Geocodio supports batch processing."""
        return GeocodeServiceType.BATCH

    @property
    def requires_api_key(self) -> bool:
        """Geocodio requires an API key."""
        return True

    def prepare_addresses(self, voters: list[Voter]) -> list[str]:
        """Format voter addresses for Geocodio batch API.

        The Geocodio API expects a JSON array of address strings:
        ["123 Main St, City, ST ZIP", ...]

        Args:
            voters: List of Voter model instances

        Returns:
            List of formatted address strings ready for submission
        """
        addresses = []
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
            addresses.append(address)

        if skipped > 0:
            logger.info(f"Skipped {skipped} voters with incomplete addresses")

        logger.debug(f"Prepared {len(addresses)} addresses for Geocodio batch")
        return addresses

    def submit_request(self, prepared_data: list[str]) -> dict[str, Any]:
        """Submit batch geocoding request to Geocodio API.

        Args:
            prepared_data: List of address strings from prepare_addresses()

        Returns:
            JSON response dictionary from Geocodio API

        Raises:
            httpx.HTTPError: On HTTP errors
            httpx.TimeoutException: On request timeout
            ValueError: If API key is not configured
        """
        if not self.geocodio_config.api_key:
            raise ValueError(
                "Geocodio API key not configured. "
                "Set VOTE_MATCH_GEOCODE_SERVICES__GEOCODIO__API_KEY environment variable."
            )

        url = f"{self.geocodio_config.base_url}/{self.geocodio_config.api_version}/geocode"

        batch_size = len(prepared_data)
        logger.info(
            f"Submitting batch of {batch_size} addresses to Geocodio API "
            f"(timeout: {self.geocodio_config.timeout}s)"
        )

        try:
            # Submit request with timeout
            with httpx.Client(timeout=self.geocodio_config.timeout) as client:
                response = client.post(
                    url,
                    params={"api_key": self.geocodio_config.api_key},
                    headers={"Content-Type": "application/json"},
                    json=prepared_data,
                )
                response.raise_for_status()

            logger.info(f"Received response from Geocodio API ({len(response.text)} bytes)")
            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code in [401, 403]:
                logger.error("Geocodio API authentication failed - check API key")
            else:
                logger.error(f"Geocodio API HTTP error: {e}")
            raise

        except httpx.TimeoutException:
            logger.error(f"Geocodio API request timed out after {self.geocodio_config.timeout}s")
            raise

        except httpx.HTTPError as e:
            logger.error(f"Geocodio API error: {e}")
            raise

    def parse_response(
        self, response: dict[str, Any], voters: list[Voter]
    ) -> list[StandardGeocodeResult]:
        """Parse Geocodio API response into standardized results.

        The Geocodio API returns JSON with format:
        {
            "results": [
                {
                    "query": "address string",
                    "response": {
                        "results": [
                            {
                                "location": {"lat": float, "lng": float},
                                "formatted_address": "string",
                                "accuracy": float,  # 0.0-1.0
                                "accuracy_type": "rooftop|range_interpolation|...",
                                ...
                            }
                        ]
                    }
                },
                ...
            ]
        }

        Args:
            response: Parsed JSON response from Geocodio API
            voters: Original list of voters (for matching results)

        Returns:
            List of StandardGeocodeResult objects
        """
        results = []

        # Get the results array from response
        response_results = response.get("results", [])

        if len(response_results) != len(voters):
            logger.warning(
                f"Response count ({len(response_results)}) does not match "
                f"voter count ({len(voters)})"
            )

        # Process each result (order should match input order)
        for i, item in enumerate(response_results):
            if i >= len(voters):
                logger.warning(f"Extra result at index {i} with no matching voter")
                break

            voter = voters[i]
            registration_number = voter.voter_registration_number
            query = item.get("query", "")

            # Get the response object for this address
            address_response = item.get("response", {})
            geocode_results = address_response.get("results", [])

            # Handle case where no results were found
            if not geocode_results or len(geocode_results) == 0:
                result = StandardGeocodeResult(
                    voter_id=registration_number,
                    service_name=self.service_name,
                    status=GeocodeQuality.NO_MATCH,
                    longitude=None,
                    latitude=None,
                    matched_address=None,
                    match_confidence=None,
                    raw_response={"query": query, "response": address_response},
                    error_message=None,
                )
                results.append(result)
                logger.debug(f"No match found for voter {registration_number}")
                continue

            # Use the first (best) result
            best_result = geocode_results[0]

            # Extract coordinates
            location = best_result.get("location", {})
            latitude = location.get("lat")
            longitude = location.get("lng")

            # Extract matched address
            matched_address = best_result.get("formatted_address")

            # Extract accuracy score (0.0-1.0)
            accuracy = best_result.get("accuracy", 0.0)

            # Map accuracy_type to quality status
            accuracy_type = best_result.get("accuracy_type", "").lower()

            if accuracy_type in ["rooftop", "point"]:
                status = GeocodeQuality.EXACT
            elif accuracy_type in ["range_interpolation", "nearest_rooftop_match"]:
                status = GeocodeQuality.INTERPOLATED
            elif accuracy_type in ["street_center", "place", "county", "state"]:
                status = GeocodeQuality.APPROXIMATE
            else:
                # Unknown accuracy type, use APPROXIMATE as fallback
                logger.warning(
                    f"Unknown accuracy_type '{accuracy_type}' for voter {registration_number}"
                )
                status = GeocodeQuality.APPROXIMATE

            # Create standardized result
            result = StandardGeocodeResult(
                voter_id=registration_number,
                service_name=self.service_name,
                status=status,
                longitude=longitude,
                latitude=latitude,
                matched_address=matched_address,
                match_confidence=accuracy,  # Use accuracy directly (0.0-1.0)
                raw_response={
                    "query": query,
                    "response": best_result,  # Store the full result for debugging
                },
                error_message=None,
            )

            results.append(result)
            logger.debug(f"Parsed result for voter {registration_number}: {status.value}")

        logger.info(f"Parsed {len(results)} results from Geocodio response")
        return results
