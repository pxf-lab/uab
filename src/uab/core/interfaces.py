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


class AssetLibraryPlugin(Plugin, ABC):
    """
    Abstract base class for asset library plugins.

    Plugins provide access to asset sources (local files, remote sources, etc.)
    and handle searching, downloading, and asset management.

    Concrete subclasses auto-register via __init_subclass__ into this
    class's own registry, accessible via the getters.
    """

    # Registry for all concrete implementations of this plugin type
    _implementations: dict[str, type["AssetLibraryPlugin"]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-register concrete plugin subclasses."""
        super().__init_subclass__(**kwargs)
        # Only register concrete classes with a plugin_id
        if cls.plugin_id:
            AssetLibraryPlugin._implementations[cls.plugin_id] = cls

    @classmethod
    def get_all(cls) -> dict[str, type["AssetLibraryPlugin"]]:
        """Return dict of plugin_id → plugin class."""
        return cls._implementations.copy()

    @classmethod
    def get(cls, plugin_id: str) -> type["AssetLibraryPlugin"] | None:
        """Get a specific plugin class by ID."""
        return cls._implementations.get(plugin_id)

    @classmethod
    def reset_registry(cls) -> None:
        """Clear registry (for testing)."""
        cls._implementations.clear()

    @abstractmethod
    async def search(self, query: str) -> list[StandardAsset]:
        """
        Search for assets matching the query.

        Args:
            query: Search string (empty string returns all/default assets)

        Returns:
            List of matching StandardAsset objects
        """
        ...

    @abstractmethod
    async def download(
        self, asset: StandardAsset, resolution: str | None = None
    ) -> StandardAsset:
        """
        Download a cloud asset to local storage.

        Args:
            asset: The asset to download
            resolution: Optional resolution preference (e.g., "1k", "2k", "4k")

        Returns:
            Updated StandardAsset with local_path and status=LOCAL

        Raises:
            NotImplementedError: If plugin doesn't support downloads
        """
        ...

    @property
    @abstractmethod
    def can_download(self) -> bool:
        """True if this plugin supports downloading assets."""
        ...

    @property
    @abstractmethod
    def can_remove(self) -> bool:
        """True if this plugin supports removing assets."""
        ...

    def get_settings_schema(self, asset: StandardAsset) -> dict[str, Any] | None:
        """
        Return options schema for import settings dialog.

        Override to provide asset-specific import options.

        Args:
            asset: The asset being imported

        Returns:
            Schema dict or None if no settings needed.
            Schema format:
            {
                "field_name": {
                    "type": "choice" | "text" | "bool",
                    "options": [...],  # for choice type
                    "default": value
                }
            }
        """
        return None


class HostIntegration(ABC):
    """
    Abstract base class for DCC host integrations.

    Handles importing assets into the host application (Houdini, Maya, etc.)
    and manages renderer detection and material creation.
    """

    @property
    @abstractmethod
    def uab_supported_renderers(self) -> list[str]:
        """
        Return a list of renderers that are supported by UAB.

        Returns:
            List of renderer identifiers (e.g., "arnold", "redshift", "karma")
        """
        ...

    @abstractmethod
    def import_asset(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        """
        Import an asset into the host application's scene. Delegates to the appropriate
        renderer strategy.

        Wrap operations in an undo group where supported.

        Args:
            asset: The asset to import (must have local_path set)
            options: Import options from settings dialog
        """
        ...

    @abstractmethod
    def update_selection(self, asset: StandardAsset) -> None:
        """
        Where supported, update the selection in the host application. Delegates
        to the appropriate renderer strategy.

        Ex. in Houdini, update the selected node with the new asset.
        """
        ...

    @abstractmethod
    def get_host_available_renderers(self) -> list[str]:
        """
        Return a list of renderers that are available in the host application.

        Returns:
            List of renderer identifiers (e.g., "arnold", "redshift", "karma")
        """
        ...

    @abstractmethod
    def get_active_renderer(self) -> str:
        """
        Detect and return the active renderer.

        Returns:
            Renderer identifier (e.g., "arnold", "redshift", "karma")
        """
        ...
