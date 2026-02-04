"""Geocoding service implementations."""

# Services will auto-register on import
# Import all service modules here to ensure registration
from . import census  # noqa: F401
from . import geocodio  # noqa: F401
from . import google_maps  # noqa: F401
from . import mapbox  # noqa: F401
from . import nominatim  # noqa: F401
from . import photon  # noqa: F401

__all__ = ["census", "nominatim", "geocodio", "mapbox", "photon", "google_maps"]
