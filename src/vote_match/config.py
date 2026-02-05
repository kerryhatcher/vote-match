"""Configuration management for Vote Match using pydantic-settings."""

from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceConfig(BaseModel):
    """Base configuration for a geocoding service."""

    enabled: bool = True
    timeout: int = 60
    rate_limit_delay: float = 0.0  # Seconds between requests
    batch_size: Optional[int] = None  # Service-specific default batch size


class CensusConfig(ServiceConfig):
    """Configuration for Census Geocoder."""

    benchmark: str = "Public_AR_Current"
    vintage: str = "Current_Current"
    timeout: int = 300


class NominatimConfig(ServiceConfig):
    """Configuration for Nominatim (OpenStreetMap) Geocoder."""

    base_url: str = "https://nominatim.openstreetmap.org"
    email: Optional[str] = None  # Required by usage policy
    rate_limit_delay: float = 1.0  # OSM requires 1 req/sec max
    timeout: int = 30
    batch_size: int = 10  # Small batches for frequent progress saves


class MapboxConfig(ServiceConfig):
    """Configuration for Mapbox Geocoding API."""

    api_key: Optional[str] = None
    base_url: str = "https://api.mapbox.com"
    api_version: str = "v6"  # v6 has batch support
    rate_limit_delay: float = 0.06  # 1000/min = ~0.06s
    timeout: int = 60
    batch_size: int = 100  # Conservative (supports up to 1000)
    country: str = "us"  # Filter results to US


class GeocodioConfig(ServiceConfig):
    """Configuration for Geocodio API."""

    api_key: Optional[str] = None
    base_url: str = "https://api.geocod.io"
    api_version: str = "v1.9"
    rate_limit_delay: float = 0.0  # Batch endpoint not rate limited
    timeout: int = 600  # 10 min for large batches
    batch_size: int = 1000  # Conservative (supports up to 10,000)


class PhotonConfig(ServiceConfig):
    """Configuration for Photon (Komoot) Geocoder."""

    base_url: str = "https://photon.komoot.io"
    timeout: int = 30


class GoogleMapsConfig(ServiceConfig):
    """Configuration for Google Maps Geocoder."""

    api_key: Optional[str] = None
    region: str = "us"
    timeout: int = 60


class OpenCageConfig(ServiceConfig):
    """Configuration for OpenCage Geocoder."""

    api_key: Optional[str] = None
    timeout: int = 60


class GeocodeServicesConfig(BaseModel):
    """Container for all geocoding service configurations."""

    census: CensusConfig = Field(default_factory=CensusConfig)
    nominatim: NominatimConfig = Field(default_factory=NominatimConfig)
    mapbox: MapboxConfig = Field(default_factory=MapboxConfig)
    geocodio: GeocodioConfig = Field(default_factory=GeocodioConfig)
    photon: PhotonConfig = Field(default_factory=PhotonConfig)
    google: GoogleMapsConfig = Field(default_factory=GoogleMapsConfig)
    opencage: OpenCageConfig = Field(default_factory=OpenCageConfig)


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_prefix="VOTE_MATCH_",
        env_file=".env",
        env_nested_delimiter="__",  # VOTE_MATCH_GEOCODE_SERVICES__CENSUS__BENCHMARK
    )

    database_url: str = Field(
        default="postgresql+psycopg://vote_match:vote_match_dev@localhost:5432/vote_match",
        description="PostgreSQL database URL for SQLAlchemy",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    log_file: str = Field(
        default="logs/vote-match.log",
        description="Path to log file",
    )
    default_state: str = Field(
        default="GA",
        description="Default state code for voter data",
    )
    default_batch_size: int = Field(
        default=5000,
        description="Default batch size for processing records",
    )

    # Geocoding service configurations
    geocode_services: GeocodeServicesConfig = Field(default_factory=GeocodeServicesConfig)
    default_geocode_service: str = Field(
        default="census", description="Default geocoding service to use"
    )

    # Legacy Census configuration (deprecated - use geocode_services.census instead)
    census_benchmark: str = Field(
        default="Public_AR_Current",
        description="[DEPRECATED] Use geocode_services.census.benchmark",
    )
    census_vintage: str = Field(
        default="Current_Current",
        description="[DEPRECATED] Use geocode_services.census.vintage",
    )
    census_timeout: int = Field(
        default=300,
        description="[DEPRECATED] Use geocode_services.census.timeout",
    )

    # USPS configuration (address validation, not geocoding)
    usps_client_id: str = Field(
        default="",
        description="USPS API OAuth2 Client ID",
    )
    usps_client_secret: str = Field(
        default="",
        description="USPS API OAuth2 Client Secret",
    )
    usps_base_url: str = Field(
        default="https://apis.usps.com/addresses/v3",
        description="USPS API base URL (use https://apis-tem.usps.com/addresses/v3 for testing)",
    )
    usps_timeout: int = Field(
        default=60,
        description="Timeout for USPS API requests in seconds",
    )

    # Cloudflare R2 configuration (S3-compatible object storage)
    r2_enabled: bool = Field(
        default=False,
        description="Enable Cloudflare R2 upload for generated maps",
    )
    r2_endpoint_url: str = Field(
        default="",
        description="Cloudflare R2 endpoint URL (format: https://<account-id>.r2.cloudflarestorage.com)",
    )
    r2_access_key_id: str = Field(
        default="",
        description="R2 API Token Access Key ID (from R2 > Manage R2 API Tokens)",
    )
    r2_secret_access_key: str = Field(
        default="",
        description="R2 API Token Secret Access Key (from R2 > Manage R2 API Tokens)",
    )
    r2_bucket_name: str = Field(
        default="",
        description="R2 bucket name for map uploads",
    )
    r2_public_url: str = Field(
        default="",
        description="Public URL for accessing uploaded maps (custom domain or R2.dev subdomain)",
    )
    r2_folder: str = Field(
        default="",
        description="Optional folder path in R2 bucket for map uploads (e.g., '304urhg4ugh02u8hg430u8hg2439u84rgh')",
    )


def get_settings() -> Settings:
    """Get application settings instance."""
    return Settings()
