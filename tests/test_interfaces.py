from uab.core.interfaces import AssetLibraryPlugin
from uab.core.models import StandardAsset


class DummyLibraryPlugin(AssetLibraryPlugin):
    plugin_id = "dummy"
    display_name = "Dummy Library"

    async def search(self, query: str) -> list[StandardAsset]:
        return []

    async def download(
        self, asset: StandardAsset, resolution: str | None = None
    ) -> StandardAsset:
        return asset

    @property
    def can_download(self) -> bool:
        return False

    @property
    def can_remove(self) -> bool:
        return True
