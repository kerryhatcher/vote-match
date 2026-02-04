"""Photon (Komoot) geocoding service implementation."""

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
class PhotonGeocoder(GeocodeService):
    """Photon (Komoot) geocoding service.

    Photon is a free, open-source geocoding service based on OpenStreetMap data.
    Rate limit: 1 request per second (recommended for free service).
    Coverage: Global.
    """

    def __init__(self, config: Settings):
        """Initialize Photon geocoder with configuration.

        Args:
            config: Application settings containing photon configuration
        """
        super().__init__(config)
        self.photon_config = config.geocode_services.photon

    @property
    def service_name(self) -> str:
        """Unique identifier for this service."""
        return "photon"

    @property
    def service_type(self) -> GeocodeServiceType:
        """Photon requires individual requests (not batch)."""
        return GeocodeServiceType.INDIVIDUAL

    @property
    def requires_api_key(self) -> bool:
        """Photon is free and requires no API key."""
        return False

    def prepare_addresses(self, voters: list[Voter]) -> list[dict[str, Any]]:
        """Format voter addresses for Photon API.

        Args:
            voters: List of Voter model instances

        Returns:
            List of prepared address dictionaries for Photon
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

            # Prepare Photon query
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

        logger.debug(f"Prepared {len(prepared)} addresses for Photon")
        return prepared

    def submit_request(self, prepared_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Submit geocoding requests to Photon API.

        Photon requires individual requests with rate limiting.

        Args:
            prepared_data: List of prepared address dictionaries

        Returns:
            List of raw responses from Photon
        """
        results = []

        logger.info(
            f"Submitting {len(prepared_data)} requests to Photon API "
            f"(rate limit: {self.photon_config.rate_limit_delay}s per request)"
        )

        with httpx.Client(timeout=self.photon_config.timeout) as client:
            for i, address in enumerate(prepared_data, 1):
                # Apply rate limiting
                if i > 1 and self.photon_config.rate_limit_delay > 0:
                    time.sleep(self.photon_config.rate_limit_delay)

                try:
                    # Photon search endpoint
                    params = {
                        "q": address["query"],
                        "limit": 1,  # Only return best match
                    }

                    # User-Agent header for courtesy
                    headers = {"User-Agent": "VoteMatch/1.0 (voter registration geocoding tool)"}

                    response = client.get(
                        f"{self.photon_config.base_url}/api",
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

        logger.info(f"Completed {len(results)} Photon requests")
        return results

    def parse_response(
        self, response: list[dict[str, Any]], voters: list[Voter]
    ) -> list[StandardGeocodeResult]:
        """Parse Photon responses into standardized results.

        Photon returns GeoJSON FeatureCollection:
        {
            "features": [
                {
                    "geometry": {"coordinates": [lon, lat], "type": "Point"},
                    "properties": {
                        "name": "street name",
                        "city": "city name",
                        "state": "state name",
                        "osm_key": "addr|highway|place",
                        "osm_type": "N|W|R",
                        ...
                    }
                }
            ]
        }

        Args:
            response: List of raw responses from Photon
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
            features = response_data.get("features", [])

            if not features or len(features) == 0:
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
                # Match found - use first feature
                feature = features[0]
                geometry = feature.get("geometry", {})
                properties = feature.get("properties", {})

                # Extract coordinates (GeoJSON format: [lon, lat])
                coordinates = geometry.get("coordinates", [])
                if len(coordinates) >= 2:
                    longitude = float(coordinates[0])
                    latitude = float(coordinates[1])
                else:
                    longitude = None
                    latitude = None

                # Build matched address from properties
                address_parts = []
                if properties.get("name"):
                    address_parts.append(properties["name"])
                if properties.get("city"):
                    address_parts.append(properties["city"])
                if properties.get("state"):
                    address_parts.append(properties["state"])

                matched_address = ", ".join(address_parts) if address_parts else None

                # Infer quality from OSM key (Photon doesn't provide confidence scores)
                # OSM keys categorized by precision level:
                # - addr: Specific address point
                # - highway: Street-level match
                # - building: Building footprint (specific but not address-level)
                # - amenity/shop: Point of interest (restaurant, store, etc.)
                # - place: City/neighborhood level
                # - landuse: Land use area (park, forest, etc.)
                osm_key = properties.get("osm_key", "").lower()

                if osm_key == "addr":
                    # Address-level match (highest precision)
                    status = GeocodeQuality.EXACT
                    match_confidence = 0.9
                elif osm_key == "highway":
                    # Street-level match
                    status = GeocodeQuality.INTERPOLATED
                    match_confidence = 0.7
                elif osm_key == "building":
                    # Building footprint - specific but not address-level
                    status = GeocodeQuality.APPROXIMATE
                    match_confidence = 0.5
                elif osm_key in ("amenity", "shop"):
                    # POI (restaurant, store, etc.) - lower than building
                    status = GeocodeQuality.APPROXIMATE
                    match_confidence = 0.45
                elif osm_key == "place":
                    # City/neighborhood level
                    status = GeocodeQuality.APPROXIMATE
                    match_confidence = 0.5
                elif osm_key == "landuse":
                    # Land use area (park, forest) - lowest precision
                    status = GeocodeQuality.APPROXIMATE
                    match_confidence = 0.4
                else:
                    # Unknown OSM key - rare edge cases
                    logger.warning(
                        f"Unknown OSM key '{osm_key}' for voter {voter_id}, "
                        f"defaulting to APPROXIMATE"
                    )
                    status = GeocodeQuality.APPROXIMATE
                    match_confidence = 0.5

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
                            "response": feature,
                            "osm_key": osm_key,
                        },
                        error_message=None,
                    )
                )

                logger.debug(
                    f"Parsed result for voter {voter_id}: {status.value} (osm_key={osm_key})"
                )

        logger.info(f"Parsed {len(results)} results from Photon responses")
        return results
