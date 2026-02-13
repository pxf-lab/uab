"""Abstract base classes and plugin registry for UAB."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol, TypeAlias, runtime_checkable

from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
    StandardAsset,
)


@runtime_checkable
class Browsable(Protocol):
    """Common interface for anything the browser can display."""

    id: str
    name: str
    source: str
    thumbnail_url: str | None
    thumbnail_path: Path | None

    @property
    def display_status(self) -> AssetStatus:
        """Status to show in UI (may be derived for composites)."""
        ...


# Type alias for composite children
Composable: TypeAlias = Asset | CompositeAsset


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
    async def search(self, query: str) -> list[Browsable]:
        """
        Search for assets matching the query.

        Args:
            query: Search string (empty string returns all/default assets)

        Returns:
            List of matching Browsable items
        """
        ...

    async def expand_composite(self, composite: CompositeAsset) -> CompositeAsset:
        """
        Expand a composite item (lazy-load/populate its children).

        Plugins that return `CompositeAsset` items should override this.
        """
        raise NotImplementedError

    async def download_asset(self, asset: Asset) -> Asset:
        """
        Download a single-file `Asset` to local storage.

        Plugins that support downloads should override this.
        """
        raise NotImplementedError

    async def download_composite(
        self,
        composite: CompositeAsset,
        resolution: str | None = None,
        recursive: bool = True,
    ) -> CompositeAsset:
        """
        Download a `CompositeAsset`.

        Plugins should typically download all descendant `Asset`s, optionally
        filtered by `resolution` (plugin-specific semantics).
        """
        raise NotImplementedError

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

    def get_settings_schema(self, item: object) -> dict[str, Any] | None:
        """
        Return options schema for import settings dialog.

        Override to provide item-specific import options (Asset or CompositeAsset).

        Args:
            item: The item being imported

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


@runtime_checkable
class SupportsLocalImport(Protocol):
    """
    Protocol for plugins that support importing local files.

    Plugins implementing this protocol can import files from the filesystem
    and add them to the asset library.
    """

    def add_assets(self, paths: Path | list[Path]) -> list[Browsable]:
        """
        Add assets from files or directories.

        Accepts either a single path or list of paths. Each path can be:
        - A file: Added directly if it has a supported extension
        - A directory: Scanned recursively for supported files

        Args:
            paths: Single path or list of paths (files or directories)

        Returns:
            List of top-level Browsable items that were added (Assets and/or CompositeAssets)
        """
        ...


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

    def import_composite(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """
        Import a `CompositeAsset` into the host.

        Default implementation dispatches by `composite.composite_type`.
        Integrations should override the corresponding `_import_*` methods.
        """
        if composite.composite_type in (CompositeType.MATERIAL, CompositeType.TEXTURE):
            return self._import_material(composite, options)
        if composite.composite_type == CompositeType.HDRI:
            return self._import_hdri_composite(composite, options)
        if composite.composite_type == CompositeType.MODEL:
            return self._import_model_composite(composite, options)

        raise ValueError(f"Unsupported composite type: {composite.composite_type}")

    def _import_material(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """Import a MATERIAL composite."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement _import_material()"
        )

    def _import_hdri_composite(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """Import an HDRI composite."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement _import_hdri_composite()"
        )

    def _import_model_composite(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """Import a MODEL composite."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement _import_model_composite()"
        )

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

    @property
    def supports_replace_selection(self) -> bool:
        """
        Whether this host supports replacing/updating a selected node.

        When True, the context menu will show a "Replace <asset>" option
        that calls update_selection() on the currently selected node.

        Returns:
            True if the host supports node replacement, False otherwise.
        """
        return False

    @property
    def supports_import(self) -> bool:
        """
        Whether this host supports import actions from the browser UI.

        Hosts can disable this globally (e.g., standalone mode) to hide import
        affordances for all plugins.
        """
        return True

    def get_node_label_for_asset_type(self, asset_type: AssetType) -> str:
        """
        Return the host-specific node label for an asset type.

        Used in context menu labels like "New Environment Light" or "Replace Material".

        Args:
            asset_type: The type of asset (HDRI, TEXTURE, MODEL)

        Returns:
            Human-readable label (e.g., "Environment Light", "Material", "Geometry")
        """
        return asset_type.value.title()


class RenderStrategy(ABC):
    """
    Abstract base class for renderer-specific asset operations.
    """

    @abstractmethod
    def get_required_texture_maps(self) -> set[str]:
        """
        Return required texture-map keys for material import.

        Note: This set may contain naming variants; any one of the returned
        keys can satisfy the requirement (e.g., diffuse/base_color/albedo).
        """
        ...

    def get_optional_texture_maps(self) -> set[str]:
        """
        Return optional texture-map keys for material import.

        Missing optional maps should not block import, but may be logged.
        """
        return {"normal", "roughness", "metallic", "ao", "displacement"}

    @abstractmethod
    def create_environment_light(
        self, composite: CompositeAsset, options: dict[str, Any]
    ) -> Any:
        """
        Create an environment light from a composite.

        Args:
            composite: The composite to create environment light from
            options: Environment light creation options

        Returns:
            The created environment light node/network/etc (type depends on host)
        """
        ...

    @abstractmethod
    def update_environment_light(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        """
        Update an environment light from the asset.

        Args:
            asset: The asset to update environment light from
            options: Environment light update options

        Returns:
            The updated environment light node/network/etc (type depends on host)
        """
        ...

    @abstractmethod
    def create_material_from_textures(
        self, name: str, textures: dict[str, Path], options: dict[str, Any]
    ) -> Any:
        """
        Create a material from a set of texture file paths.

        Args:
            name: Material display name
            textures: Dict of role/map key -> local texture path
            options: Material creation options

        Returns:
            The created material node/network/etc (type depends on host)
        """
        ...

    @abstractmethod
    def create_material(
        self, composite: CompositeAsset, options: dict[str, Any]
    ) -> Any:
        """
        Create a material from a composite in the host application.

        Args:
            composite: The composite to create material from
            options: Material creation options

        Returns:
            The created material node/network/etc (type depends on host)
        """
        ...

    @abstractmethod
    def update_material(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        """
        Update a material from the asset.

        Args:
            asset: The asset to update material from
            options: Material update options
        """
        ...
