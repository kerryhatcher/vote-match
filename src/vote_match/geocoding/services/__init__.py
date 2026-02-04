"""Geocoding service implementations."""

# Services will auto-register on import
# Import all service modules here to ensure registration
from . import census  # noqa: F401

__all__ = ["census"]
