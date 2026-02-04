"""USPS Address Validation API integration."""

import time
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

from vote_match.config import Settings
from vote_match.models import Voter


@dataclass
class USPSValidationResult:
    """Result from USPS address validation for a single address."""

    registration_number: str
    status: str  # 'validated', 'corrected', 'failed'

    # Validated address components (from USPS response)
    street_address: str | None
    city: str | None
    state: str | None
    zipcode: str | None
    zipplus4: str | None

    # Additional USPS metadata
    delivery_point: str | None
    carrier_route: str | None
    dpv_confirmation: str | None  # Y/D/S/N
    business: str | None  # Y/N
    vacant: str | None  # Y/N

    # For logging/debugging
    error_message: str | None = None


class USPSOAuthTokenCache:
    """Simple token cache to avoid requesting a new token for every request."""

    def __init__(self):
        self.token: str | None = None
        self.expires_at: float = 0.0

    def get_token(self, settings: Settings) -> str:
        """Get cached token or fetch a new one if expired."""
        current_time = time.time()

        # Return cached token if still valid (with 60s buffer)
        if self.token and current_time < (self.expires_at - 60):
            logger.debug("Using cached OAuth token")
            return self.token

        # Fetch new token
        logger.info("Fetching new USPS OAuth token")
        self.token = _fetch_oauth_token(settings)
        # USPS tokens typically expire in 3600 seconds (1 hour)
        self.expires_at = current_time + 3600
        return self.token


# Global token cache instance
_token_cache = USPSOAuthTokenCache()


def _fetch_oauth_token(settings: Settings) -> str:
    """
    Fetch OAuth2 access token from USPS API using Client Credentials flow.

    Args:
        settings: Application settings with USPS credentials.

    Returns:
        Bearer access token string.

    Raises:
        httpx.HTTPError: If token request fails.
    """
    # Extract base URL without path
    base_url = settings.usps_base_url.rsplit("/addresses/", 1)[0]
    token_url = f"{base_url}/oauth2/v3/token"

    data = {
        "grant_type": "client_credentials",
        "client_id": settings.usps_client_id,
        "client_secret": settings.usps_client_secret,
        "scope": "addresses",
    }

    try:
        with httpx.Client(timeout=settings.usps_timeout) as client:
            response = client.post(token_url, data=data)
            response.raise_for_status()

        token_data = response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            msg = "No access_token in OAuth response"
            logger.error(msg)
            raise ValueError(msg)

        logger.debug("Successfully obtained USPS OAuth token")
        return access_token

    except httpx.TimeoutException:
        logger.error("USPS OAuth token request timed out after {}s", settings.usps_timeout)
        raise
    except httpx.HTTPError as e:
        logger.error("USPS OAuth token request failed: {}", str(e))
        raise


def validate_address(
    voter: Voter,
    token: str,
    settings: Settings,
) -> USPSValidationResult:
    """
    Validate a single voter address using USPS Address Validation API.

    Args:
        voter: Voter object with address to validate.
        token: OAuth2 Bearer token.
        settings: Application settings.

    Returns:
        USPSValidationResult with validation status and validated address.
    """
    registration_number = voter.voter_registration_number

    # Build address from voter components
    street_address = voter.build_street_address()

    # Check required fields
    if not street_address:
        logger.warning("Voter {} missing street address", registration_number)
        return USPSValidationResult(
            registration_number=registration_number,
            status="failed",
            street_address=None,
            city=None,
            state=None,
            zipcode=None,
            zipplus4=None,
            delivery_point=None,
            carrier_route=None,
            dpv_confirmation=None,
            business=None,
            vacant=None,
            error_message="Missing street address",
        )

    # USPS requires state and either city or ZIP
    state = "GA"  # Default state (could be made configurable)
    city = voter.residence_city
    zipcode = voter.residence_zipcode

    if not state or (not city and not zipcode):
        logger.warning(
            "Voter {} missing required fields (state={}, city={}, zip={})",
            registration_number,
            state,
            city,
            zipcode,
        )
        return USPSValidationResult(
            registration_number=registration_number,
            status="failed",
            street_address=None,
            city=None,
            state=None,
            zipcode=None,
            zipplus4=None,
            delivery_point=None,
            carrier_route=None,
            dpv_confirmation=None,
            business=None,
            vacant=None,
            error_message="Missing required fields (state, city or ZIP)",
        )

    # Build API request
    url = f"{settings.usps_base_url}/address"
    headers = {
        "Authorization": f"Bearer {token}",
    }
    params: dict[str, Any] = {
        "streetAddress": street_address,
        "state": state,
    }

    if city:
        params["city"] = city
    if zipcode:
        params["ZIPCode"] = zipcode
    if voter.residence_apt_unit_number:
        params["secondaryAddress"] = voter.residence_apt_unit_number

    # Call USPS API
    try:
        with httpx.Client(timeout=settings.usps_timeout) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()

        response_data = response.json()
        logger.debug("USPS validation response for {}: {}", registration_number, response_data)

        # Parse response
        return _parse_usps_response(voter, response_data)

    except httpx.HTTPStatusError as e:
        # Handle specific HTTP errors
        status_code = e.response.status_code
        error_msg = f"HTTP {status_code}"

        try:
            error_data = e.response.json()
            if "error" in error_data and "message" in error_data["error"]:
                error_msg = error_data["error"]["message"]
        except Exception:
            pass

        logger.warning(
            "USPS validation failed for {} with status {}: {}",
            registration_number,
            status_code,
            error_msg,
        )

        return USPSValidationResult(
            registration_number=registration_number,
            status="failed",
            street_address=None,
            city=None,
            state=None,
            zipcode=None,
            zipplus4=None,
            delivery_point=None,
            carrier_route=None,
            dpv_confirmation=None,
            business=None,
            vacant=None,
            error_message=error_msg,
        )

    except httpx.TimeoutException:
        logger.warning("USPS validation timed out for {}", registration_number)
        return USPSValidationResult(
            registration_number=registration_number,
            status="failed",
            street_address=None,
            city=None,
            state=None,
            zipcode=None,
            zipplus4=None,
            delivery_point=None,
            carrier_route=None,
            dpv_confirmation=None,
            business=None,
            vacant=None,
            error_message="Request timeout",
        )

    except Exception as e:
        logger.error("USPS validation error for {}: {}", registration_number, str(e))
        return USPSValidationResult(
            registration_number=registration_number,
            status="failed",
            street_address=None,
            city=None,
            state=None,
            zipcode=None,
            zipplus4=None,
            delivery_point=None,
            carrier_route=None,
            dpv_confirmation=None,
            business=None,
            vacant=None,
            error_message=str(e),
        )


def _parse_usps_response(voter: Voter, response_data: dict) -> USPSValidationResult:
    """
    Parse USPS API response into USPSValidationResult.

    Args:
        voter: Original voter record for comparison.
        response_data: JSON response from USPS API.

    Returns:
        USPSValidationResult with parsed data.
    """
    registration_number = voter.voter_registration_number

    # Extract address fields from response
    address = response_data.get("address", {})
    additional_info = response_data.get("additionalInfo", {})

    validated_street = address.get("streetAddress")
    validated_city = address.get("city")
    validated_state = address.get("state")
    validated_zip = address.get("ZIPCode")
    validated_zip4 = address.get("ZIPPlus4")

    # Extract additional metadata
    delivery_point = additional_info.get("deliveryPoint")
    carrier_route = additional_info.get("carrierRoute")
    dpv_confirmation = additional_info.get("DPVConfirmation")
    business = additional_info.get("business")
    vacant = additional_info.get("vacant")

    # Determine if address was corrected by comparing to original
    original_street = voter.build_street_address()
    original_city = voter.residence_city
    original_zip = voter.residence_zipcode

    # Normalize for comparison (case-insensitive, strip whitespace)
    def normalize(s: str | None) -> str:
        return (s or "").strip().upper()

    address_corrected = (
        normalize(validated_street) != normalize(original_street)
        or normalize(validated_city) != normalize(original_city)
        or normalize(validated_zip) != normalize(original_zip)
    )

    status = "corrected" if address_corrected else "validated"

    logger.debug(
        "Voter {} validation status: {} (original='{}', validated='{}')",
        registration_number,
        status,
        original_street,
        validated_street,
    )

    return USPSValidationResult(
        registration_number=registration_number,
        status=status,
        street_address=validated_street,
        city=validated_city,
        state=validated_state,
        zipcode=validated_zip,
        zipplus4=validated_zip4,
        delivery_point=delivery_point,
        carrier_route=carrier_route,
        dpv_confirmation=dpv_confirmation,
        business=business,
        vacant=vacant,
        error_message=None,
    )


def validate_batch(
    voters: list[Voter],
    settings: Settings,
) -> list[USPSValidationResult]:
    """
    Validate a batch of voter addresses using USPS API.

    Note: USPS API does not have a batch endpoint, so this validates
    addresses one at a time with rate limiting.

    Args:
        voters: List of Voter objects to validate.
        settings: Application settings.

    Returns:
        List of USPSValidationResult objects.
    """
    results = []

    # Get OAuth token (cached)
    try:
        token = _token_cache.get_token(settings)
    except Exception as e:
        logger.error("Failed to obtain USPS OAuth token: {}", str(e))
        # Return all as failed
        return [
            USPSValidationResult(
                registration_number=voter.voter_registration_number,
                status="failed",
                street_address=None,
                city=None,
                state=None,
                zipcode=None,
                zipplus4=None,
                delivery_point=None,
                carrier_route=None,
                dpv_confirmation=None,
                business=None,
                vacant=None,
                error_message="OAuth token acquisition failed",
            )
            for voter in voters
        ]

    logger.info("Validating {} addresses with USPS API", len(voters))

    # Validate each address with rate limiting
    for i, voter in enumerate(voters):
        result = validate_address(voter, token, settings)
        results.append(result)

        # Rate limiting: 50ms delay between requests to avoid 429 errors
        # This allows ~20 requests per second
        if i < len(voters) - 1:  # Don't sleep after the last request
            time.sleep(0.05)

        # Log progress every 50 records
        if (i + 1) % 50 == 0:
            logger.info("Validated {}/{} addresses", i + 1, len(voters))

    logger.info("USPS validation complete: {} addresses processed", len(results))

    return results
