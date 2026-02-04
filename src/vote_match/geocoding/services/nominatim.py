"""Nominatim (OpenStreetMap) geocoding service implementation."""

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
class NominatimGeocoder(GeocodeService):
    """Nominatim (OpenStreetMap) geocoding service.

    Nominatim is a free, open-source geocoding service based on OpenStreetMap data.
    Rate limit: 1 request per second (enforced by rate_limit_delay).
    Requires: email address in configuration (usage policy requirement).
    """

    def __init__(self, config: Settings):
        """Initialize Nominatim geocoder with configuration.

        Args:
            config: Application settings containing nominatim configuration
        """
        super().__init__(config)
        self.nominatim_config = config.geocode_services.nominatim

    @property
    def service_name(self) -> str:
        """Unique identifier for this service."""
        return "nominatim"

    @property
    def service_type(self) -> GeocodeServiceType:
        """Nominatim requires individual requests (not batch)."""
        return GeocodeServiceType.INDIVIDUAL

    @property
    def requires_api_key(self) -> bool:
        """Nominatim is free and requires no API key."""
        return False

    def prepare_addresses(self, voters: list[Voter]) -> list[dict[str, Any]]:
        """Format voter addresses for Nominatim API.

        Args:
            voters: List of Voter model instances

        Returns:
            List of prepared address dictionaries for Nominatim
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

            # Prepare Nominatim query
            # Format: street, city, state zipcode
            state = self.config.default_state
            query = f"{street}, {city}, {state}"
            if zipcode:
                query += f" {zipcode}"

            prepared.append(
                {
                    "voter_id": voter.voter_registration_number,
                    "query": query,
                }
            )

        logger.debug(f"Prepared {len(prepared)} addresses for Nominatim")
        return prepared

    def submit_request(self, prepared_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Submit geocoding requests to Nominatim API.

        Nominatim requires individual requests with rate limiting.

        Args:
            prepared_data: List of prepared address dictionaries

        Returns:
            List of raw responses from Nominatim
        """
        results = []

        logger.info(
            f"Submitting {len(prepared_data)} requests to Nominatim API "
            f"(rate limit: {self.nominatim_config.rate_limit_delay}s per request)"
        )

        with httpx.Client(timeout=self.nominatim_config.timeout) as client:
            for i, address in enumerate(prepared_data, 1):
                # Apply rate limiting
                if i > 1 and self.nominatim_config.rate_limit_delay > 0:
                    time.sleep(self.nominatim_config.rate_limit_delay)

                try:
                    # Nominatim search endpoint
                    params = {
                        "q": address["query"],
                        "format": "json",
                        "addressdetails": 1,
                        "limit": 1,
                        "countrycodes": "us",  # Limit to US addresses
                    }

                    # Build User-Agent header (required by Nominatim usage policy)
                    if self.nominatim_config.email:
                        user_agent = f"VoteMatch/1.0 ({self.nominatim_config.email})"
                    else:
                        user_agent = "VoteMatch/1.0 (voter registration geocoding tool)"

                    headers = {"User-Agent": user_agent}

                    response = client.get(
                        f"{self.nominatim_config.base_url}/search",
                        params=params,
                        headers=headers,
                    )
                    response.raise_for_status()

                    results.append(
                        {
                            "voter_id": address["voter_id"],
                            "query": address["query"],
                            "response": response.json(),
                            "status": "success",
                        }
                    )

                    if i % 50 == 0:
                        logger.info(f"Processed {i}/{len(prepared_data)} requests")

                except httpx.HTTPError as e:
                    logger.warning(f"Request failed for voter {address['voter_id']}: {e}")
                    results.append(
                        {
                            "voter_id": address["voter_id"],
                            "query": address["query"],
                            "response": None,
                            "status": "failed",
                            "error": str(e),
                        }
                    )

        logger.info(f"Completed {len(results)} Nominatim requests")
        return results

    def parse_response(
        self, response: list[dict[str, Any]], voters: list[Voter]
    ) -> list[StandardGeocodeResult]:
        """Parse Nominatim responses into standardized results.

        Args:
            response: List of raw responses from Nominatim
            voters: Original list of voters (for matching results)

        Returns:
            List of StandardGeocodeResult objects
        """
        results = []

        for item in response:
            voter_id = item["voter_id"]

            # Handle failed requests
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
                        raw_response={"query": item["query"]},
                        error_message=item.get("error"),
                    )
                )
                continue

            # Parse successful response
            response_data = item["response"]

            if not response_data or len(response_data) == 0:
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
                            "query": item["query"],
                            "response": response_data,
                        },
                        error_message=None,
                    )
                )
            else:
                # Match found
                match = response_data[0]

                # Extract coordinates
                latitude = float(match["lat"])
                longitude = float(match["lon"])

                # Extract matched address
                matched_address = match.get("display_name", "")

                # Determine quality based on Nominatim's importance and type
                # Higher importance scores (0.0-1.0) indicate better matches
                importance = float(match.get("importance", 0.5))

                # Map to our quality levels
                if importance >= 0.8:
                    status = GeocodeQuality.EXACT
                elif importance >= 0.5:
                    status = GeocodeQuality.INTERPOLATED
                else:
                    status = GeocodeQuality.APPROXIMATE

                # Use importance as confidence score
                match_confidence = importance

                results.append(
                    StandardGeocodeResult(
                        voter_id=voter_id,
                        service_name=self.service_name,
                        status=status,
                        longitude=longitude,
                        latitude=latitude,
                        matched_address=matched_address,
                        match_confidence=match_confidence,
                        raw_response={
                            "query": item["query"],
                            "response": match,
                        },
                        error_message=None,
                    )
                )

                logger.debug(
                    f"Parsed result for voter {voter_id}: {status.value} "
                    f"(importance={importance:.2f})"
                )

        logger.info(f"Parsed {len(results)} results from Nominatim responses")
        return results
