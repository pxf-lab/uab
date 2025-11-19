import pathlib as pl
import requests
from datetime import datetime


class AssetService:
    def __init__(self, server_url: str, asset_directory_path: str):
        self.url = server_url
        self.asset_directory_path = pl.Path(asset_directory_path)

    def get_assets(self):
        try:
            response = requests.get(f"{self.url}/assets")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching assets: {e}")

    def get_asset_by_id(self, asset_id: int):
        try:
            response = requests.get(f"{self.url}/assets/{asset_id}")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error getting asset with id {asset_id}: {e}")

    def search_assets(self, text: str):
        try:
            response = requests.get(
                f"{self.url}/assets/search", params={"name": text})
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error searching assets: {e}")

    def set_asset_directory(self, directory_path: str):
        """Update the asset directory and recreate the sync service."""
        self.asset_directory_path = pl.Path(directory_path)

    def add_asset_to_db(self, asset_request_body: dict):
        asset_name = asset_request_body.get("name", "unknown")
        asset_path = asset_request_body.get("path", "")
        try:
            response = requests.post(
                f"{self.url}/assets", json=asset_request_body)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error posting asset {asset_name} at {asset_path}: {e}")

    def remove_asset_from_db(self, asset_id: int):
        try:
            response = requests.delete(f"{self.url}/assets/{asset_id}")
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error deleting asset with id {asset_id}: {e}")

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
        date_added: str | None = None,
    ) -> dict:
        return {
            "name": name or pl.Path(asset_path).name,
            "path": str(asset_path),
            "description": description,
            "preview_image_file_path": preview_image_file_path,
            "tags": tags or [],
            "author": author,
            "date_created": date_created or datetime.now().isoformat(),
            "date_added": date_added or datetime.now().isoformat(),
        }
