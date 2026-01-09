"""Abstract base classes and plugin registry for UAB."""

from abc import ABC, abstractmethod
from typing import Any

from uab.core.models import StandardAsset


class Plugin:
    """
    Base class for all plugin types.

    Plugin type ABCs inherit from this class to auto-register by class name.
    Concrete implementations set plugin_id and display_name, and register
    with their respective type's own registry.

    Example:
        class AssetLibraryPlugin(Plugin, ABC):
            ...
        # Registered as "AssetLibraryPlugin" in Plugin._plugin_types
    """

    # Registry for all plugin types
    _plugin_types: dict[str, type] = {}

    # Override in concrete subclasses
    plugin_id: str = ""
    display_name: str = ""
    description: str = ""
    author_name: str = ""
    author_email: str = ""
    documentation_url: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-register plugin type subclasses by class name."""
        super().__init_subclass__(**kwargs)
        Plugin._plugin_types[cls.__name__] = cls

    @classmethod
    def get_all_types(cls) -> dict[str, type]:
        """Return dict of class name → plugin type class."""
        return cls._plugin_types.copy()

    @classmethod
    def get_type(cls, name: str) -> type | None:
        """Get a specific plugin type by class name."""
        return cls._plugin_types.get(name)

    @classmethod
    def reset_types(cls) -> None:
        """Clear registry (for testing)."""
        cls._plugin_types.clear()
