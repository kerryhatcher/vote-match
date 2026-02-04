"""Geocoding services for Vote Match.

This package provides a flexible, extensible architecture for geocoding
voter addresses using multiple geocoding services.
"""

from .base import (
    GeocodeService,
    GeocodeServiceType,
    GeocodeQuality,
    StandardGeocodeResult,
)
from .registry import GeocodeServiceRegistry

__all__ = [
    "GeocodeService",
    "GeocodeServiceType",
    "GeocodeQuality",
    "StandardGeocodeResult",
    "GeocodeServiceRegistry",
]
