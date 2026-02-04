"""Abstract base classes for geocoding services."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class GeocodeServiceType(Enum):
    """Types of geocoding services."""

    BATCH = "batch"  # Processes multiple addresses at once
    INDIVIDUAL = "individual"  # One address per request


class GeocodeQuality(Enum):
    """Quality levels for geocoded results."""

    EXACT = "exact"
    INTERPOLATED = "interpolated"
    APPROXIMATE = "approximate"
    NO_MATCH = "no_match"
    FAILED = "failed"


@dataclass
class StandardGeocodeResult:
    """Normalized result structure for all geocoding services."""

    voter_id: int
    service_name: str
    status: GeocodeQuality
    longitude: Optional[float]
    latitude: Optional[float]
    matched_address: Optional[str]
    match_confidence: Optional[float]  # 0.0-1.0 standardized score
    raw_response: dict[str, Any]  # Service-specific data for debugging
    error_message: Optional[str] = None


class GeocodeService(ABC):
    """Abstract base class for all geocoding services."""

    def __init__(self, config: Any):
        """Initialize the service with configuration.

        Args:
            config: Settings object containing service-specific configuration
        """
        self.config = config

    @property
    @abstractmethod
    def service_name(self) -> str:
        """Unique identifier for this service."""
        pass

    @property
    @abstractmethod
    def service_type(self) -> GeocodeServiceType:
        """Whether this service supports batch or individual processing."""
        pass

    @property
    @abstractmethod
    def requires_api_key(self) -> bool:
        """Whether this service requires API authentication."""
        pass

    @abstractmethod
    def prepare_addresses(self, voters: list[Any]) -> Any:
        """Format voter addresses for this service's API.

        Args:
            voters: List of Voter model instances

        Returns:
            Service-specific prepared data structure
        """
        pass

    @abstractmethod
    def submit_request(self, prepared_data: Any) -> Any:
        """Submit geocoding request to service API.

        Args:
            prepared_data: Data prepared by prepare_addresses()

        Returns:
            Raw response from the service
        """
        pass

    @abstractmethod
    def parse_response(
        self, response: Any, voters: list[Any]
    ) -> list[StandardGeocodeResult]:
        """Parse service response into standardized results.

        Args:
            response: Raw response from submit_request()
            voters: Original list of Voter instances (for matching results)

        Returns:
            List of StandardGeocodeResult objects
        """
        pass

    def geocode_batch(self, voters: list[Any]) -> list[StandardGeocodeResult]:
        """Main workflow: prepare → submit → parse.

        Args:
            voters: List of Voter model instances

        Returns:
            List of StandardGeocodeResult objects
        """
        prepared = self.prepare_addresses(voters)
        response = self.submit_request(prepared)
        return self.parse_response(response, voters)
