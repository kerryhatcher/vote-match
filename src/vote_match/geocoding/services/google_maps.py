"""Google Maps Geocoding API service implementation."""

import time
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
class GoogleMapsGeocoder(GeocodeService):
    """Google Maps Geocoding API implementation.

    Premium quality geocoding service with excellent coverage.
    Rate limit: 50 requests per second.
    Coverage: Global.
    """

    def __init__(self, config: Settings):
        """Initialize Google Maps geocoder with configuration.

        Args:
            config: Application settings containing google maps configuration
        """
        super().__init__(config)
        self.google_config = config.geocode_services.google

    @property
    def service_name(self) -> str:
        """Unique identifier for this service."""
        return "google"

    @property
    def service_type(self) -> GeocodeServiceType:
        """Google Maps requires individual requests (no batch support)."""
        return GeocodeServiceType.INDIVIDUAL

    @property
    def requires_api_key(self) -> bool:
        """Google Maps requires an API key."""
        return True

    def prepare_addresses(self, voters: list[Voter]) -> list[dict[str, Any]]:
        """Format voter addresses for Google Maps API.

        Args:
            voters: List of Voter model instances

        Returns:
            List of prepared address dictionaries for Google Maps
        """
        prepared = []

        for voter in voters:
            # Build street address
            street = voter.build_street_address()
            city = voter.residence_city
            zipcode = voter.residence_zipcode

            # Skip voters with missing required fields
            if not street or not city:
                logger.debug(
                    f"Skipping voter {voter.voter_registration_number} "
                    f"due to missing address fields"
                )
                continue

            # Prepare Google Maps query
            # Format: street, city, state zipcode
            state = self.config.default_state
            address = f"{street}, {city}, {state}"
            if zipcode:
                address += f" {zipcode}"

            prepared.append(
                {
                    "voter_id": voter.voter_registration_number,
                    "address": address,
                }
            )

        logger.debug(f"Prepared {len(prepared)} addresses for Google Maps")
        return prepared

    def submit_request(self, prepared_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Submit geocoding requests to Google Maps API.

        Google Maps requires individual requests with rate limiting.

        Args:
            prepared_data: List of prepared address dictionaries

        Returns:
            List of raw responses from Google Maps

        Raises:
            ValueError: If API key is not configured
        """
        if not self.google_config.api_key:
            raise ValueError(
                "Google Maps API key not configured. "
                "Set VOTE_MATCH_GEOCODE_SERVICES__GOOGLE__API_KEY environment variable."
            )

        results = []

        logger.info(
            f"Submitting {len(prepared_data)} requests to Google Maps API "
            f"(rate limit: {self.google_config.rate_limit_delay}s per request)"
        )

        with httpx.Client(timeout=self.google_config.timeout) as client:
            for i, address_data in enumerate(prepared_data, 1):
                # Apply rate limiting
                if i > 1 and self.google_config.rate_limit_delay > 0:
                    time.sleep(self.google_config.rate_limit_delay)

                try:
                    # Google Maps Geocoding API endpoint
                    params = {
                        "address": address_data["address"],
                        "key": self.google_config.api_key,
                        "region": self.google_config.region,  # Bias to region (e.g., "us")
                    }

                    response = client.get(
                        "https://maps.googleapis.com/maps/api/geocode/json",
                        params=params,
                    )
                    response.raise_for_status()

                    results.append(
                        {
                            "voter_id": address_data["voter_id"],
                            "address": address_data["address"],
                            "response": response.json(),
                            "status": "success",
                        }
                    )

                    if i % 50 == 0:
                        logger.info(f"Processed {i}/{len(prepared_data)} requests")

                except httpx.HTTPStatusError as e:
                    if e.response.status_code in [401, 403]:
                        logger.error("Google Maps API authentication failed - check API key")
                    elif e.response.status_code == 429:
                        logger.warning("Google Maps API rate limit exceeded")

                    results.append(
                        {
                            "voter_id": address_data["voter_id"],
                            "address": address_data["address"],
                            "response": None,
                            "status": "failed",
                            "error": str(e),
                        }
                    )

                except httpx.HTTPError as e:
                    logger.warning(f"Request failed for voter {address_data['voter_id']}: {e}")
                    results.append(
                        {
                            "voter_id": address_data["voter_id"],
                            "address": address_data["address"],
                            "response": None,
                            "status": "failed",
                            "error": str(e),
                        }
                    )

        logger.info(f"Completed {len(results)} Google Maps requests")
        return results

    def parse_response(
        self, response: list[dict[str, Any]], voters: list[Voter]
    ) -> list[StandardGeocodeResult]:
        """Parse Google Maps responses into standardized results.

        Google Maps returns JSON (not GeoJSON):
        {
            "status": "OK|ZERO_RESULTS|OVER_QUERY_LIMIT|REQUEST_DENIED|...",
            "results": [
                {
                    "formatted_address": "string",
                    "geometry": {
                        "location": {"lat": float, "lng": float},
                        "location_type": "ROOFTOP|RANGE_INTERPOLATED|GEOMETRIC_CENTER|APPROXIMATE"
                    },
                    ...
                }
            ]
        }

        Args:
            response: List of raw responses from Google Maps
            voters: Original list of voters (for matching results)

        Returns:
            List of StandardGeocodeResult objects
        """
        results = []

        for item in response:
            voter_id = item["voter_id"]

            # Handle failed HTTP requests
            if item["status"] == "failed":
                results.append(
                    StandardGeocodeResult(
                        voter_id=voter_id,
                        service_name=self.service_name,
                        status=GeocodeQuality.FAILED,
                        longitude=None,
                        latitude=None,
                        matched_address=None,
                        match_confidence=None,
                        raw_response={"address": item["address"]},
                        error_message=item.get("error"),
                    )
                )
                continue

            # Parse successful HTTP response
            response_data = item["response"]
            api_status = response_data.get("status", "")

            # Check API status codes
            if api_status == "ZERO_RESULTS":
                # No match found
                results.append(
                    StandardGeocodeResult(
                        voter_id=voter_id,
                        service_name=self.service_name,
                        status=GeocodeQuality.NO_MATCH,
                        longitude=None,
                        latitude=None,
                        matched_address=None,
                        match_confidence=None,
                        raw_response={
                            "address": item["address"],
                            "response": response_data,
                        },
                        error_message=None,
                    )
                )
            elif api_status == "REQUEST_DENIED":
                # API key or permission issue
                results.append(
                    StandardGeocodeResult(
                        voter_id=voter_id,
                        service_name=self.service_name,
                        status=GeocodeQuality.FAILED,
                        longitude=None,
                        latitude=None,
                        matched_address=None,
                        match_confidence=None,
                        raw_response={"address": item["address"], "response": response_data},
                        error_message="API request denied - check API key and permissions",
                    )
                )
            elif api_status == "OVER_QUERY_LIMIT":
                # Rate limit or quota exceeded
                results.append(
                    StandardGeocodeResult(
                        voter_id=voter_id,
                        service_name=self.service_name,
                        status=GeocodeQuality.FAILED,
                        longitude=None,
                        latitude=None,
                        matched_address=None,
                        match_confidence=None,
                        raw_response={"address": item["address"], "response": response_data},
                        error_message="API query limit exceeded",
                    )
                )
            elif api_status == "OK":
                # Successful match
                geocode_results = response_data.get("results", [])

                if not geocode_results or len(geocode_results) == 0:
                    # Shouldn't happen with OK status, but handle gracefully
                    results.append(
                        StandardGeocodeResult(
                            voter_id=voter_id,
                            service_name=self.service_name,
                            status=GeocodeQuality.NO_MATCH,
                            longitude=None,
                            latitude=None,
                            matched_address=None,
                            match_confidence=None,
                            raw_response={"address": item["address"], "response": response_data},
                            error_message=None,
                        )
                    )
                else:
                    # Use first (best) result
                    best_result = geocode_results[0]

                    # Extract coordinates
                    location = best_result.get("geometry", {}).get("location", {})
                    latitude = location.get("lat")
                    longitude = location.get("lng")

                    # Extract matched address
                    matched_address = best_result.get("formatted_address")

                    # Map location_type to quality status
                    location_type = best_result.get("geometry", {}).get("location_type", "")

                    if location_type == "ROOFTOP":
                        status = GeocodeQuality.EXACT
                        confidence = 1.0
                    elif location_type == "RANGE_INTERPOLATED":
                        status = GeocodeQuality.INTERPOLATED
                        confidence = 0.85
                    elif location_type == "GEOMETRIC_CENTER":
                        status = GeocodeQuality.APPROXIMATE
                        confidence = 0.6
                    elif location_type == "APPROXIMATE":
                        status = GeocodeQuality.APPROXIMATE
                        confidence = 0.5
                    else:
                        # Unknown location type
                        logger.warning(
                            f"Unknown location_type '{location_type}' for voter {voter_id}"
                        )
                        status = GeocodeQuality.APPROXIMATE
                        confidence = 0.5

                    results.append(
                        StandardGeocodeResult(
                            voter_id=voter_id,
                            service_name=self.service_name,
                            status=status,
                            longitude=longitude,
                            latitude=latitude,
                            matched_address=matched_address,
                            match_confidence=confidence,
                            raw_response={
                                "address": item["address"],
                                "response": best_result,
                                "location_type": location_type,
                            },
                            error_message=None,
                        )
                    )

                    logger.debug(
                        f"Parsed result for voter {voter_id}: {status.value} "
                        f"(location_type={location_type})"
                    )
            else:
                # Unknown or error status
                results.append(
                    StandardGeocodeResult(
                        voter_id=voter_id,
                        service_name=self.service_name,
                        status=GeocodeQuality.FAILED,
                        longitude=None,
                        latitude=None,
                        matched_address=None,
                        match_confidence=None,
                        raw_response={"address": item["address"], "response": response_data},
                        error_message=f"Unknown API status: {api_status}",
                    )
                )

        logger.info(f"Parsed {len(results)} results from Google Maps responses")
        return results
