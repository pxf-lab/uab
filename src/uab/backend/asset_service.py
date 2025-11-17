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

    @staticmethod
    def create_asset_req_body_from_path(
        asset_path: str,
        tags: list[str] | None = None,
        author: str | None = None,
    ):
        """Create a request body matching the new schema."""
        return {
            "name": pl.Path(asset_path).name,
            "path": str(asset_path),
            "description": None,
            "preview_image_file_path": None,
            "tags": tags or [],
            "author": author,
            "date_created": datetime.now().isoformat(),
            "date_added": datetime.now().isoformat(),
        }
