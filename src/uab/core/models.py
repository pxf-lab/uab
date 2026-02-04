"""Data models for Universal Asset Browser."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias, Union
from uuid import uuid4
import warnings

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from uab.core.schemas import CompositeTypeSchema


class AssetStatus(str, Enum):
    """Asset download/availability status for a single-file asset (the new Asset type)."""

    CLOUD = "cloud"  # Available in cloud, not downloaded
    DOWNLOADING = "downloading"  # Currently downloading
    LOCAL = "local"  # Downloaded and available locally


class AssetType(str, Enum):
    """Type of asset."""
    # TODO: make this more easily extensible

    TEXTURE = "texture"  # Texture maps (diffuse, normal, etc.)
    MODEL = "model"  # 3D geometry files
    HDRI = "hdri"  # HDR environment images


class CompositeType(str, Enum):
    """Type of composite asset grouping.

    Composite types describe *groupings* of one or more leaf `Asset`s, potentially
    nested recursively via other `CompositeAsset`s.
    """

    # Leaf-level composites (contain only Assets)
    TEXTURE = "texture"
    MODEL = "model"
    HDRI = "hdri"

    # Nested composites (contain other composites and/or assets)
    MATERIAL = "material"
    MODEL_SET = "model_set"
    HDRI_SET = "hdri_set"
    CHARACTER = "character"
    SCENE = "scene"


@dataclass
class Asset:
    """A single-file asset (one resolution/LOD/format of one item)."""

    id: str
    source: str
    external_id: str
    name: str
    asset_type: AssetType
    status: AssetStatus
    local_path: Path | None = None
    remote_url: str | None = None
    thumbnail_url: str | None = None
    thumbnail_path: Path | None = None
    file_size: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize enum values and paths."""
        if isinstance(self.local_path, str):
            self.local_path = Path(self.local_path)
        if isinstance(self.thumbnail_path, str):
            self.thumbnail_path = Path(self.thumbnail_path)

        if isinstance(self.asset_type, str):
            self.asset_type = AssetType(self.asset_type)
        if isinstance(self.status, str):
            self.status = AssetStatus(self.status)

        if not self.id:
            self.id = f"{self.source}-{self.name}-{str(uuid4())}"

    @property
    def display_status(self) -> AssetStatus:
        """Status to show in UI (direct for single-file assets)."""
        return self.status

    # Backwards-compatible alias for pre-refactor code paths
    @property
    def type(self) -> AssetType:  # noqa: A003 - keep name for compatibility
        return self.asset_type

    @type.setter
    def type(self, value: AssetType | str) -> None:  # noqa: A003 - keep name for compatibility
        self.asset_type = AssetType(value) if isinstance(value, str) else value

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization (e.g., database storage)."""
        return {
            "id": self.id,
            "source": self.source,
            "external_id": self.external_id,
            "name": self.name,
            "asset_type": self.asset_type.value,
            "status": self.status.value,
            "local_path": str(self.local_path) if self.local_path else None,
            "remote_url": self.remote_url,
            "thumbnail_url": self.thumbnail_url,
            "thumbnail_path": str(self.thumbnail_path) if self.thumbnail_path else None,
            "file_size": self.file_size,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Asset":
        """Create instance from dictionary (e.g., database retrieval)."""
        local_path = data.get("local_path")
        thumbnail_path = data.get("thumbnail_path")

        return cls(
            id=data.get("id", ""),
            source=data.get("source", ""),
            external_id=data.get("external_id", ""),
            name=data.get("name", ""),
            asset_type=AssetType(
                data.get("asset_type", AssetType.TEXTURE.value)),
            status=AssetStatus(data.get("status", AssetStatus.CLOUD.value)),
            local_path=Path(local_path) if local_path else None,
            remote_url=data.get("remote_url"),
            thumbnail_url=data.get("thumbnail_url"),
            thumbnail_path=Path(thumbnail_path) if thumbnail_path else None,
            file_size=data.get("file_size"),
            metadata=data.get("metadata", {}),
        )


Composable: TypeAlias = Union[Asset, "CompositeAsset"]


@dataclass
class CompositeAsset:
    """A named collection of Assets and/or other CompositeAssets."""

    id: str
    source: str
    external_id: str
    name: str
    composite_type: CompositeType
    thumbnail_url: str | None = None
    thumbnail_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    children: list[Composable] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.thumbnail_path, str):
            self.thumbnail_path = Path(self.thumbnail_path)
        if isinstance(self.composite_type, str):
            self.composite_type = CompositeType(self.composite_type)
        if not self.id:
            self.id = f"{self.source}-{self.name}-{str(uuid4())}"

    def _collect_leaf_statuses(self) -> set[AssetStatus]:
        """Recursively collect statuses of all leaf Assets."""
        statuses: set[AssetStatus] = set()
        for child in self.children:
            if isinstance(child, Asset):
                statuses.add(child.status)
            elif isinstance(child, CompositeAsset):
                statuses.update(child._collect_leaf_statuses())
        return statuses

    @property
    def display_status(self) -> AssetStatus:
        """Status to show in UI (derived from descendant Assets)."""
        if not self.children:
            return AssetStatus.CLOUD

        statuses = self._collect_leaf_statuses()
        if not statuses:
            return AssetStatus.CLOUD
        if AssetStatus.DOWNLOADING in statuses:
            return AssetStatus.DOWNLOADING
        if statuses == {AssetStatus.LOCAL}:
            return AssetStatus.LOCAL
        if statuses == {AssetStatus.CLOUD}:
            return AssetStatus.CLOUD

        # TODO: this needs to be mixed but keeping this default for UI compatibility for now
        return AssetStatus.CLOUD

    @property
    def has_local_children(self) -> bool:
        """True if any descendant Asset is LOCAL."""
        return AssetStatus.LOCAL in self._collect_leaf_statuses()

    @property
    def has_cloud_children(self) -> bool:
        """True if any descendant Asset is CLOUD."""
        return AssetStatus.CLOUD in self._collect_leaf_statuses()

    @property
    def is_mixed(self) -> bool:
        """True if composite has both local and cloud descendants."""
        statuses = self._collect_leaf_statuses()
        return AssetStatus.LOCAL in statuses and AssetStatus.CLOUD in statuses

    def get_all_assets(self) -> list[Asset]:
        """Recursively collect all leaf Assets."""
        assets: list[Asset] = []
        for child in self.children:
            if isinstance(child, Asset):
                assets.append(child)
            elif isinstance(child, CompositeAsset):
                assets.extend(child.get_all_assets())
        return assets

    def get_local_assets(self) -> list[Asset]:
        """Get all local leaf Assets."""
        return [a for a in self.get_all_assets() if a.status == AssetStatus.LOCAL]

    def get_child_by_role(self, role: str) -> Composable | None:
        """Find a direct child by its role metadata."""
        for child in self.children:
            meta = getattr(child, "metadata", None)
            if isinstance(meta, dict) and meta.get("role") == role:
                return child
        return None

    def get_children_by_type(self, child_type: type) -> list[Composable]:
        """Return direct children that match the given type."""
        return [child for child in self.children if isinstance(child, child_type)]

    # Schema helpers

    def get_schema(self) -> CompositeTypeSchema:
        """Get the schema for this composite type."""
        from uab.core.schemas import get_schema

        return get_schema(self.composite_type)

    @property
    def present_roles(self) -> set[str]:
        """Get the set of roles present in direct children (via metadata['role'])."""
        roles: set[str] = set()
        for child in self.children:
            meta = getattr(child, "metadata", None)
            if not isinstance(meta, dict):
                continue
            role = meta.get("role")
            if isinstance(role, str) and role:
                roles.add(role)
        return roles

    def is_complete(self) -> bool:
        """Check if all required roles are present per the schema."""
        schema = self.get_schema()
        if not schema.required_roles:
            return True
        return schema.required_roles <= self.present_roles

    def get_missing_roles(self) -> set[str]:
        """Get required roles that are missing."""
        schema = self.get_schema()
        if not schema.required_roles:
            return set()
        return schema.required_roles - self.present_roles

    def validate(self) -> list[str]:
        """Validate this composite against its schema. Returns list of warnings."""
        warnings: list[str] = []
        schema = self.get_schema()

        missing = self.get_missing_roles()
        if missing:
            warnings.append(
                f"Missing required roles: {', '.join(sorted(missing))}"
            )

        # Unknown roles (direct children)
        for role in sorted(self.present_roles):
            if not schema.is_role_valid(role):
                warnings.append(
                    f"Unknown role '{role}' for {self.composite_type.value}"
                )

        allowed = tuple(schema.allowed_child_types)
        for child in self.children:
            if allowed and not isinstance(child, allowed):
                warnings.append(
                    f"Child type {type(child).__name__} not allowed in {self.composite_type.value}"
                )

            if isinstance(child, Asset) and schema.child_asset_type is not None:
                if child.asset_type != schema.child_asset_type:
                    warnings.append(
                        f"Asset '{child.name}' is {child.asset_type.value}, expected {schema.child_asset_type.value}"
                    )

            if (
                isinstance(child, CompositeAsset)
                and schema.expected_child_composite_types
                and child.composite_type not in schema.expected_child_composite_types
            ):
                expected = ", ".join(
                    sorted(ct.value for ct in schema.expected_child_composite_types)
                )
                warnings.append(
                    f"Child composite '{child.name}' is {child.composite_type.value}, expected one of: {expected}"
                )

        return warnings

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary (children serialized recursively)."""
        return {
            "id": self.id,
            "source": self.source,
            "external_id": self.external_id,
            "name": self.name,
            "composite_type": self.composite_type.value,
            "thumbnail_url": self.thumbnail_url,
            "thumbnail_path": str(self.thumbnail_path) if self.thumbnail_path else None,
            "metadata": self.metadata,
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompositeAsset":
        """Deserialize from dictionary (children deserialized recursively)."""
        children: list[Composable] = []
        for child_data in data.get("children", []):
            if "composite_type" in child_data:
                children.append(CompositeAsset.from_dict(child_data))
            else:
                children.append(Asset.from_dict(child_data))

        thumbnail_path = data.get("thumbnail_path")
        return cls(
            id=data.get("id", ""),
            source=data.get("source", ""),
            external_id=data.get("external_id", ""),
            name=data.get("name", ""),
            composite_type=CompositeType(
                data.get("composite_type", CompositeType.SCENE.value)),
            thumbnail_url=data.get("thumbnail_url"),
            thumbnail_path=Path(thumbnail_path) if thumbnail_path else None,
            metadata=data.get("metadata", {}),
            children=children,
        )


def deprecated(reason: str):
    """Mark an API as deprecated (runtime-only marker)."""

    def _decorator(obj):
        setattr(obj, "__deprecated_reason__", reason)
        return obj

    return _decorator


_STANDARD_ASSET_DEPRECATION_EMITTED = False


def _warn_standard_asset_deprecated() -> None:
    """Warn once per process when StandardAsset is instantiated."""
    global _STANDARD_ASSET_DEPRECATION_EMITTED
    if _STANDARD_ASSET_DEPRECATION_EMITTED:
        return

    _STANDARD_ASSET_DEPRECATION_EMITTED = True
    message = "StandardAsset is deprecated; use Asset (single-file) instead."
    logger.warning(message)
    warnings.warn(message, DeprecationWarning, stacklevel=4)


@deprecated("Use Asset (single-file) instead. StandardAsset will be removed in a future release.")
@dataclass
class StandardAsset:
    """
    Universal asset representation used throughout the application.

    This is the common currency for all plugins and integrations.
    All asset sources (local, Poly Haven, etc.) convert to this format.

    Attributes:
        id (str): Internal UUID (generated on creation) in the format of <source>-<name>-<uuid>.
        source (str): Plugin ID (e.g., "polyhaven", "local").
        external_id (str): ID from source (API ID or filename).
        name (str): Display name.
        type (AssetType): Asset type (TEXTURE, MODEL, HDRI).
        status (AssetStatus): Download/availability status (CLOUD, DOWNLOADING, LOCAL).
        local_path (Path or None): Root directory or file path containing asset files.
            If a directory, metadata["files"] maps semantic names to filenames.
        thumbnail_url (str): Remote thumbnail URL.
        thumbnail_path (Path or None): Local cached thumbnail path.
        metadata (dict[str, Any]): Flexible payload containing files, resolutions, and other plugin-specific data.
    """

    source: str
    name: str
    type: AssetType
    status: AssetStatus
    id: str = ""
    external_id: str = ""
    local_path: Path | None = None
    thumbnail_url: str | None = ""
    thumbnail_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Convert string paths to Path objects if needed."""
        _warn_standard_asset_deprecated()
        if isinstance(self.local_path, str):
            self.local_path = Path(self.local_path)
        if isinstance(self.thumbnail_path, str):
            self.thumbnail_path = Path(self.thumbnail_path)

        # Ensure type and status are enum instances
        if isinstance(self.type, str):
            self.type = AssetType(self.type)
        if isinstance(self.status, str):
            self.status = AssetStatus(self.status)

        # Generate ID only if not provided (empty string or None)
        if not self.id:
            self.id = f"{self.source}-{self.name}-{str(uuid4())}"

    @property
    def display_status(self) -> AssetStatus:
        """Status to show in UI (alias for `status`)."""
        return self.status

    def to_asset(self) -> Asset:
        """simple conversion to the new single-file `Asset` model."""
        remote_url = None
        file_size = None
        if isinstance(self.metadata, dict):
            maybe_remote = self.metadata.get("remote_url")
            if isinstance(maybe_remote, str):
                remote_url = maybe_remote
            maybe_size = self.metadata.get("file_size")
            if isinstance(maybe_size, int):
                file_size = maybe_size

        thumb_url = self.thumbnail_url or None

        return Asset(
            id=self.id,
            source=self.source,
            external_id=self.external_id,
            name=self.name,
            asset_type=self.type,
            status=self.status,
            local_path=self.local_path,
            remote_url=remote_url,
            thumbnail_url=thumb_url,
            thumbnail_path=self.thumbnail_path,
            file_size=file_size,
            metadata=self.metadata.copy() if isinstance(self.metadata, dict) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "id": self.id,
            "source": self.source,
            "external_id": self.external_id,
            "name": self.name,
            "type": self.type.value,
            "status": self.status.value,
            "local_path": str(self.local_path) if self.local_path else None,
            "thumbnail_url": self.thumbnail_url,
            "thumbnail_path": str(self.thumbnail_path) if self.thumbnail_path else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StandardAsset":
        """Create instance from dictionary (e.g., database retrieval)."""
        # Extract paths before creating instance
        local_path = data.get("local_path")
        thumbnail_path = data.get("thumbnail_path")

        return cls(
            source=data.get("source", ""),
            name=data.get("name", ""),
            type=AssetType(data.get("type", AssetType.TEXTURE.value)),
            status=AssetStatus(data.get("status", AssetStatus.CLOUD.value)),
            # Empty string triggers auto-generation in __post_init__
            id=data.get("id", ""),
            external_id=data.get("external_id", ""),
            local_path=Path(local_path) if local_path else None,
            thumbnail_url=data.get("thumbnail_url", ""),
            thumbnail_path=Path(thumbnail_path) if thumbnail_path else None,
            metadata=data.get("metadata", {}),
        )
