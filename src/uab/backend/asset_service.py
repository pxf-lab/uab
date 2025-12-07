import pathlib as pl
from datetime import datetime
from typing import Iterable, List, Sequence

import requests

from uab.core.assets import Asset


class AssetService:
    def __init__(self, server_url: str, asset_directory_path: str):
        self.url = server_url
        self.asset_directory_path = pl.Path(asset_directory_path)

    def _build_assets_from_response(self, payload: Sequence[dict]) -> List[Asset]:
        """Convert a list payload into Asset instances."""
        return [Asset.from_api_payload(item) for item in payload or []]

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
            return Asset.from_api_payload(data)
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
            return Asset.from_api_payload(response.json())
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
            return Asset.from_api_payload(response.json())
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

        Returns:
            An Asset instance ready to be added to the database.
        """
        return Asset(
            name=name or pl.Path(asset_path).name,
            path=str(asset_path),
            asset_id=None,  # Will be assigned by the server on creation
            description=description,
            preview_image_file_path=preview_image_file_path,
            tags=tags or [],
            author=author,
            date_created=date_created or datetime.now().isoformat().split('T')[
                0],
            date_added=datetime.now().isoformat().split('T')[0],
        )
