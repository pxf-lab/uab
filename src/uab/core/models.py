"""Data models for Universal Asset Browser."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4
import warnings

logger = logging.getLogger(__name__)


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
