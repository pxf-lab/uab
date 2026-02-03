from uab.core.interfaces import AssetLibraryPlugin, Browsable, Plugin
from uab.core.models import StandardAsset


class DummyLibraryPlugin(AssetLibraryPlugin):
    plugin_id = "dummy"
    display_name = "Dummy Library"

    async def search(self, query: str) -> list[Browsable]:
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


def test_plugin_type_registry_contains_asset_library() -> None:
    plugin_type = Plugin.get_type("AssetLibraryPlugin")
    assert plugin_type is AssetLibraryPlugin


def test_asset_library_registry_registers_concrete_plugins() -> None:
    assert AssetLibraryPlugin.get("dummy") is DummyLibraryPlugin
