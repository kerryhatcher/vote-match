"""Service registry for geocoding providers."""

from typing import Any

from .base import GeocodeService


class GeocodeServiceRegistry:
    """Registry for discovering and instantiating geocoding services."""

    _services: dict[str, type[GeocodeService]] = {}

    @classmethod
    def register(
        cls, service_class: type[GeocodeService]
    ) -> type[GeocodeService]:
        """Decorator to register a geocoding service.

        Args:
            service_class: GeocodeService subclass to register

        Returns:
            The same service class (for use as decorator)

        Example:
            @GeocodeServiceRegistry.register
            class CensusGeocoder(GeocodeService):
                ...
        """
        # Get service_name from class property
        # We need to instantiate temporarily to get the property value
        # or use a class attribute
        service_name = service_class.service_name.fget(None)  # type: ignore
        cls._services[service_name] = service_class
        return service_class

    @classmethod
    def get_service(cls, name: str, config: Any) -> GeocodeService:
        """Instantiate a service by name.

        Args:
            name: Service identifier (e.g., 'census', 'nominatim')
            config: Settings object to pass to service constructor

        Returns:
            Instantiated GeocodeService

        Raises:
            ValueError: If service name is not registered
        """
        if name not in cls._services:
            available = ", ".join(cls.list_services())
            raise ValueError(
                f"Unknown geocoding service: {name}. "
                f"Available services: {available}"
            )
        return cls._services[name](config)

    @classmethod
    def list_services(cls) -> list[str]:
        """List all registered service names.

        Returns:
            List of service identifiers
        """
        return sorted(list(cls._services.keys()))
