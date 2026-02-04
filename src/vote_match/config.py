"""Configuration management for Vote Match using pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(env_prefix="VOTE_MATCH_", env_file=".env")

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
        default=10000,
        description="Default batch size for processing records",
    )
    census_benchmark: str = Field(
        default="Public_AR_Current",
        description="Census geocoding benchmark",
    )
    census_vintage: str = Field(
        default="Current_Current",
        description="Census geocoding vintage",
    )
    census_timeout: int = Field(
        default=300,
        description="Timeout for Census API requests in seconds",
    )
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


def get_settings() -> Settings:
    """Get application settings instance."""
    return Settings()
