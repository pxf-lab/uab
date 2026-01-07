import pathlib as pl
from datetime import datetime
from typing import Iterable, List, Sequence

import requests

from uab.core.assets import Asset, HDRI, Texture


class AssetService:
    def __init__(self, server_url: str, asset_directory_path: str):
        self.url = server_url
        self.asset_directory_path = pl.Path(asset_directory_path)

    def _detect_asset_type(self, data: dict) -> type[Asset]:
        """Detect the appropriate Asset subclass based on file extension.

        Args:
            data: Dictionary containing asset data with a 'path' field.

        Returns:
            The appropriate Asset class (HDRI, Texture, or Asset).
        """
        path = data.get("path", "")
        if not path:
            return Asset

        path_obj = pl.Path(path)
        ext = path_obj.suffix.lower()

        # HDRI files
        if ext in [".hdr", ".exr"]:
            return HDRI

        # For now, only HDRI is supported as Texture subclass
        # Other texture types can be added here later
        return Asset

    def _build_asset_from_data(self, data: dict) -> Asset:
        """Convert a single asset payload into the appropriate Asset instance.

        Args:
            data: Dictionary containing asset data from API.

        Returns:
            An instance of Asset, HDRI, or Texture based on file type.
        """
        asset_class = self._detect_asset_type(data)

        # TODO: refactor the constructor of @HDRI
        # For HDRI, manually construct to ensure file_type is set correctly
        if asset_class == HDRI:
            # HDRI inherits from Texture, so use Texture.from_dict approach
            # but construct as HDRI to get file_type set in __init__
            hdri = HDRI(
                name=data.get("name", ""),
                path=data.get("path", ""),
                color_space=data.get("color_space"),
            )
            # Set other Asset fields
            hdri.id = data.get("id")
            hdri.description = data.get("description")
            hdri.preview_image_file_path = data.get("preview_image_file_path")
            hdri.tags = data.get("tags") or []
            hdri.author = data.get("author")
            hdri.date_created = data.get("date_created")
            hdri.date_added = data.get("date_added")
            hdri.lods = data.get("lods")
            hdri.current_lod = data.get("current_lod")
            return hdri
        elif asset_class == Texture:
            return Texture.from_dict(data)
        else:
            return Asset.from_api_payload(data)

    def _build_assets_from_response(self, payload: Sequence[dict]) -> List[Asset]:
        """Convert a list payload into Asset instances."""
        return [self._build_asset_from_data(item) for item in payload or []]

    def get_assets(self) -> list[Asset]:
        """Fetch all assets from the server as Asset objects."""
        try:
            response = requests.get(f"{self.url}/assets")
            response.raise_for_status()
            data = response.json()
            return self._build_assets_from_response(data)
        except requests.exceptions.RequestException as e:
            print(f"Error fetching assets: {e}")
            return []

    def get_asset_by_id(self, asset_id: int) -> Asset | None:
        """Fetch a single asset by id as an Asset object."""
        try:
            response = requests.get(f"{self.url}/assets/{asset_id}")
            response.raise_for_status()
            data = response.json()
            return self._build_asset_from_data(data)
        except requests.exceptions.RequestException as e:
            print(f"Error getting asset with id {asset_id}: {e}")
            return None

    def search_assets(self, text: str) -> list[Asset]:
        """Search for assets by text and return Asset objects."""
        try:
            response = requests.get(
                f"{self.url}/assets/search", params={"name": text})
            response.raise_for_status()
            data = response.json()
            return self._build_assets_from_response(data)
        except requests.exceptions.RequestException as e:
            print(f"Error searching assets: {e}")
            return []

    def set_asset_directory(self, directory_path: str):
        """Update the asset directory and recreate the sync service."""
        self.asset_directory_path = pl.Path(directory_path)

    def add_asset_to_db(self, asset: Asset) -> Asset | None:
        """
        Create a new asset in the backend.

        Args:
            asset: The Asset object to create.

        Returns:
            The created Asset object from the server, or None on error.
        """
        payload = asset.to_api_payload(include_id=False)
        asset_name = asset.name or "unknown"
        asset_path = asset.path or ""
        try:
            response = requests.post(
                f"{self.url}/assets", json=payload)
            response.raise_for_status()
            return self._build_asset_from_data(response.json())
        except requests.exceptions.RequestException as e:
            print(f"Error posting asset {asset_name} at {asset_path}: {e}")
            return None

    def remove_asset_from_db(self, asset_id: int) -> None:
        try:
            response = requests.delete(f"{self.url}/assets/{asset_id}")
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error deleting asset with id {asset_id}: {e}")

    def update_asset(self, asset: Asset) -> Asset | None:
        """
        Update an existing asset in the backend.

        Args:
            asset: The Asset object to update. Must have an id set.

        Returns:
            The updated Asset object from the server, or None on error.
        """
        if asset.id is None:
            print("Error updating asset: missing id")
            return None

        payload = asset.to_api_payload(include_id=False)
        try:
            response = requests.put(
                f"{self.url}/assets/{asset.id}", json=payload)
            response.raise_for_status()
            return self._build_asset_from_data(response.json())
        except requests.exceptions.RequestException as e:
            print(f"Error updating asset with id {asset.id}: {e}")
            return None

    # TODO: move this elsewhere
    def unregister_client(self, client_id: str):
        try:
            response = requests.post(
                f"{self.url}/unregister_client", json={"client_id": client_id})
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error unregistering client {client_id}: {e}")

    @staticmethod
    def create_asset_request_body(
        asset_path: str,
        name: str | None = None,
        description: str | None = None,
        preview_image_file_path: str | None = None,
        tags: list[str] | None = None,
        author: str | None = None,
        date_created: str | None = None,
        lods: dict[str, str] | None = None,
        current_lod: str | None = None,
        color_space: str | None = None,
    ) -> Asset:
        """
        Create an Asset object from file path and optional metadata.

        This is a convenience factory for creating new Asset instances,
        typically used when importing assets from the filesystem.

        Args:
            asset_path: Path to the asset file.
            name: Display name for the asset. Defaults to the filename if not provided.
            description: Optional description.
            preview_image_file_path: Optional path to a preview image.
            tags: Optional list of tags.
            author: Optional author name.
            date_created: Optional creation date (YYYY-MM-DD format).
                         Defaults to today if not provided.
            lods: Optional dictionary mapping LOD levels to file paths.
            current_lod: Optional currently active LOD level.
            color_space: Optional color space for texture assets.

        Returns:
            An Asset instance (HDRI, Texture, or Asset) ready to be added to the database.
        """
        path_obj = pl.Path(asset_path)
        ext = path_obj.suffix.lower()

        base_kwargs = {
            "name": name or path_obj.name,
            "path": str(asset_path),
            "asset_id": None,  # Will be assigned by the server on creation
            "description": description,
            "preview_image_file_path": preview_image_file_path,
            "tags": tags or [],
            "author": author,
            "date_created": date_created or datetime.now().isoformat().split('T')[0],
            "date_added": datetime.now().isoformat().split('T')[0],
        }

        # Create HDRI instance for .hdr and .exr files
        if ext in [".hdr", ".exr"]:
            hdri = HDRI(
                name=base_kwargs["name"],
                path=base_kwargs["path"],
                color_space=color_space,
            )
            # Set base Asset fields
            hdri.id = base_kwargs["asset_id"]
            hdri.description = base_kwargs["description"]
            hdri.preview_image_file_path = base_kwargs["preview_image_file_path"]
            hdri.tags = base_kwargs["tags"]
            hdri.author = base_kwargs["author"]
            hdri.date_created = base_kwargs["date_created"]
            hdri.date_added = base_kwargs["date_added"]
            # Set LOD data if provided
            if lods:
                hdri.lods = lods
            if current_lod is not None:
                hdri.current_lod = current_lod
            return hdri

        # For other file types, create base Asset
        return Asset(**base_kwargs)
