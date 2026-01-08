"""Data models for Universal Asset Browser."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class AssetStatus(str, Enum):
    """Asset download/availability status."""

    CLOUD = "cloud"  # Available in cloud, not downloaded
    DOWNLOADING = "downloading"  # Currently downloading
    LOCAL = "local"  # Downloaded and available locally


class AssetType(str, Enum):
    """Type of asset."""

    TEXTURE = "texture"  # Texture maps (diffuse, normal, etc.)
    MODEL = "model"  # 3D geometry files
    HDRI = "hdri"  # HDR environment images


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

    id: str
    source: str
    external_id: str = ""
    name: str
    type: AssetType
    status: AssetStatus
    local_path: Path | None = None
    thumbnail_url: str = ""
    thumbnail_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Convert string paths to Path objects if needed."""
        if isinstance(self.local_path, str):
            self.local_path = Path(self.local_path)
        if isinstance(self.thumbnail_path, str):
            self.thumbnail_path = Path(self.thumbnail_path)

        # Ensure type and status are enum instances
        if isinstance(self.type, str):
            self.type = AssetType(self.type)
        if isinstance(self.status, str):
            self.status = AssetStatus(self.status)

        self.id = f"{self.source}-{self.name}-{str(uuid4())}"
