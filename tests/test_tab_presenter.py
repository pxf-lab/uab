"""Tests for TabPresenter"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from uab.core.interfaces import AssetLibraryPlugin, HostIntegration
from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
    StandardAsset,
)


class MockHostIntegration(HostIntegration):
    """Mock host integration for testing."""

    def __init__(self) -> None:
        self.imported_assets: list[tuple[StandardAsset, dict[str, Any]]] = []
        self.imported_composites: list[tuple[CompositeAsset, dict[str, Any]]] = [
        ]

    @property
    def uab_supported_renderers(self) -> list[str]:
        return ["arnold", "redshift"]

    def import_asset(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        self.imported_assets.append((asset, options))

    def import_composite(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:  # noqa: ANN401
        self.imported_composites.append((composite, options))
        return None

    def update_selection(self, asset: StandardAsset) -> None:
        pass

    def get_host_available_renderers(self) -> list[str]:
        return ["arnold", "redshift"]

    def get_active_renderer(self) -> str:
        return "arnold"


class PresenterTestPlugin(AssetLibraryPlugin):
    """Plugin with controllable async behaviors for presenter tests."""

    plugin_id = "presenter_test"
    display_name = "Presenter Test"

    def __init__(
        self,
        items: list[object],
        *,
        plugin_id: str = "presenter_test",
        can_download: bool = True,
    ) -> None:
        self._items = items
        self.plugin_id = plugin_id
        self._can_download = can_download
        self.search_mock = MagicMock()
        self.expand_mock = AsyncMock()
        self.download_asset_mock = AsyncMock()
        self.download_composite_mock = AsyncMock()

    async def search(self, query: str):  # type: ignore[override]
        self.search_mock(query)
        return list(self._items)

    async def expand_composite(self, composite: CompositeAsset) -> CompositeAsset:
        return await self.expand_mock(composite)

    async def download_asset(self, asset: Asset) -> Asset:
        return await self.download_asset_mock(asset)

    async def download_composite(
        self, composite: CompositeAsset, resolution: str | None = None, recursive: bool = True
    ) -> CompositeAsset:
        return await self.download_composite_mock(
            composite, resolution=resolution, recursive=recursive
        )

    @property
    def can_download(self) -> bool:
        return self._can_download

    @property
    def can_remove(self) -> bool:
        return False


@pytest.fixture
def mock_view() -> MagicMock:
    """Create a mock BrowserView-like object."""
    view = MagicMock()

    # Signals
    view.search_requested = MagicMock()
    view.detail_requested = MagicMock()
    view.import_requested = MagicMock()
    view.download_requested = MagicMock()
    view.remove_requested = MagicMock()
    view.new_asset_requested = MagicMock()
    view.replace_asset_requested = MagicMock()

    view.search_requested.connect = MagicMock()
    view.detail_requested.connect = MagicMock()
    view.import_requested.connect = MagicMock()
    view.download_requested.connect = MagicMock()
    view.remove_requested.connect = MagicMock()
    view.new_asset_requested.connect = MagicMock()
    view.replace_asset_requested.connect = MagicMock()

    # Methods used by presenter
    view.set_items = MagicMock()
    view.set_loading = MagicMock()
    view.show_detail = MagicMock()
    view.set_download_progress = MagicMock()
    view.get_selected_renderer = MagicMock(return_value="arnold")
    view.set_host_actions = MagicMock()
    view.set_add_assets_enabled = MagicMock()

    return view


@pytest.fixture
def mock_host() -> MockHostIntegration:
    return MockHostIntegration()


class TestTabPresenterMilestone5:
    def test_on_detail_requested_expands_composite(self, mock_view: MagicMock, mock_host: MockHostIntegration) -> None:
        from uab.presenters.tab_presenter import TabPresenter

        material = CompositeAsset(
            id="polyhaven-rusty_metal",
            source="polyhaven",
            external_id="rusty_metal",
            name="Rusty Metal",
            composite_type=CompositeType.MATERIAL,
            children=[],
        )

        expanded = CompositeAsset(
            id=material.id,
            source=material.source,
            external_id=material.external_id,
            name=material.name,
            composite_type=material.composite_type,
            children=[
                CompositeAsset(
                    id="polyhaven-rusty_metal:diffuse",
                    source="polyhaven",
                    external_id="rusty_metal:diffuse",
                    name="diffuse",
                    composite_type=CompositeType.TEXTURE,
                    metadata={"role": "diffuse", "map_type": "diffuse"},
                    children=[],
                )
            ],
        )

        plugin = PresenterTestPlugin(items=[material])
        plugin.expand_mock.return_value = expanded

        presenter = TabPresenter(plugin=plugin, view=mock_view, host=mock_host)

        asyncio.run(presenter._do_search(""))
        presenter._on_detail_requested(material.id)

        plugin.expand_mock.assert_awaited_once()
        mock_view.show_detail.assert_called_with(expanded)

    def test_preloaded_composite_detail_indexes_leaf_for_download(
        self, mock_view: MagicMock, mock_host: MockHostIntegration, tmp_path: Path
    ) -> None:
        from uab.presenters.tab_presenter import TabPresenter

        leaf = Asset(
            id="polyhaven-abandoned_greenhouse:2k:hdr",
            source="polyhaven",
            external_id="abandoned_greenhouse:2k:hdr",
            name="abandoned_greenhouse_2k.hdr",
            asset_type=AssetType.HDRI,
            status=AssetStatus.CLOUD,
            remote_url="https://example.com/abandoned_greenhouse_2k.hdr",
            metadata={"resolution": "2k", "format": "hdr"},
        )
        composite = CompositeAsset(
            id="polyhaven-abandoned_greenhouse",
            source="polyhaven",
            external_id="abandoned_greenhouse",
            name="Abandoned Greenhouse",
            composite_type=CompositeType.HDRI,
            children=[leaf],
        )

        updated_leaf = Asset.from_dict(
            {
                **leaf.to_dict(),
                "status": AssetStatus.LOCAL.value,
                "local_path": str(tmp_path / "abandoned_greenhouse_2k.hdr"),
            }
        )

        plugin = PresenterTestPlugin(items=[composite], plugin_id="local", can_download=False)
        source_plugin = PresenterTestPlugin(items=[], plugin_id="polyhaven", can_download=True)
        source_plugin.download_asset_mock.return_value = updated_leaf

        presenter = TabPresenter(
            plugin=plugin,
            view=mock_view,
            host=mock_host,
            get_plugin_by_source=lambda source: source_plugin if source == "polyhaven" else None,
        )
        asyncio.run(presenter._do_search(""))

        # Preloaded composite: no expand call, but detail should still index descendants.
        asyncio.run(presenter._do_show_detail(composite.id))
        presenter._on_download_asset_requested(leaf.id)

        source_plugin.download_asset_mock.assert_awaited_once()

    def test_download_asset_requested_updates_single_asset(
        self, mock_view: MagicMock, mock_host: MockHostIntegration, tmp_path: Path
    ) -> None:
        from uab.presenters.tab_presenter import TabPresenter

        asset = Asset(
            id="polyhaven-rusty_metal:diffuse:2k",
            source="polyhaven",
            external_id="rusty_metal:diffuse:2k",
            name="rusty_diff_2k.png",
            asset_type=AssetType.TEXTURE,
            status=AssetStatus.CLOUD,
            remote_url="https://example.com/rusty_diff_2k.png",
            metadata={"resolution": "2k", "map_type": "diffuse"},
        )

        updated = Asset.from_dict(
            {**asset.to_dict(), "status": AssetStatus.LOCAL.value, "local_path": str(tmp_path / "file.png")})

        plugin = PresenterTestPlugin(items=[asset])
        plugin.download_asset_mock.return_value = updated

        presenter = TabPresenter(plugin=plugin, view=mock_view, host=mock_host)
        asyncio.run(presenter._do_search(""))

        payloads: list[object] = []
        presenter.download_complete.connect(lambda p: payloads.append(p))

        presenter._on_download_asset_requested(asset.id)

        plugin.download_asset_mock.assert_awaited()
        assert presenter._item_cache[asset.id].display_status == AssetStatus.LOCAL
        assert payloads and isinstance(payloads[-1], dict)
        assert asset.id in payloads[-1]["downloaded_item_ids"]

    def test_download_composite_requested_passes_resolution_filter(
        self, mock_view: MagicMock, mock_host: MockHostIntegration, tmp_path: Path
    ) -> None:
        from uab.presenters.tab_presenter import TabPresenter

        composite = CompositeAsset(
            id="polyhaven-simple_chair",
            source="polyhaven",
            external_id="simple_chair",
            name="Simple Chair",
            composite_type=CompositeType.MODEL,
            children=[],
        )

        local_asset = Asset(
            id="polyhaven-simple_chair:gltf:2k",
            source="polyhaven",
            external_id="simple_chair:gltf:2k",
            name="chair_2k.gltf",
            asset_type=AssetType.MODEL,
            status=AssetStatus.LOCAL,
            local_path=tmp_path / "chair_2k.gltf",
            remote_url="https://example.com/chair_2k.gltf",
            metadata={"format": "gltf", "resolution": "2k"},
        )
        updated = CompositeAsset.from_dict(
            {**composite.to_dict(), "children": [local_asset.to_dict()]})

        plugin = PresenterTestPlugin(items=[composite])
        plugin.download_composite_mock.return_value = updated

        presenter = TabPresenter(plugin=plugin, view=mock_view, host=mock_host)
        asyncio.run(presenter._do_search(""))

        payloads: list[object] = []
        presenter.download_complete.connect(lambda p: payloads.append(p))

        presenter._on_download_composite_requested(composite.id, "2k")

        plugin.download_composite_mock.assert_awaited()
        last_call = plugin.download_composite_mock.await_args
        assert last_call.kwargs["resolution"] == "2k"
        assert payloads and local_asset.id in payloads[-1]["downloaded_item_ids"]

    def test_import_composite_calls_host_import_composite(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        from uab.presenters.tab_presenter import TabPresenter

        material = CompositeAsset(
            id="polyhaven-rusty_metal",
            source="polyhaven",
            external_id="rusty_metal",
            name="Rusty Metal",
            composite_type=CompositeType.MATERIAL,
            children=[],
        )

        expanded = CompositeAsset.from_dict(
            {
                **material.to_dict(),
                "children": [],
            }
        )

        plugin = PresenterTestPlugin(items=[material])
        plugin.expand_mock.return_value = expanded

        presenter = TabPresenter(plugin=plugin, view=mock_view, host=mock_host)
        asyncio.run(presenter._do_search(""))

        presenter._on_import_requested(material.id)

        assert len(mock_host.imported_composites) == 1
        imported, options = mock_host.imported_composites[0]
        assert imported.id == material.id
        assert options["renderer"] == "arnold"

    def test_import_composite_uses_source_plugin_settings_schema(
        self, mock_view: MagicMock, mock_host: MockHostIntegration, tmp_path: Path
    ) -> None:
        from uab.presenters.tab_presenter import TabPresenter

        leaf = Asset(
            id="polyhaven-auto_service:2k:hdr",
            source="polyhaven",
            external_id="auto_service:2k:hdr",
            name="auto_service_2k.hdr",
            asset_type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=tmp_path / "auto_service_2k.hdr",
            metadata={"resolution": "2k", "format": "hdr"},
        )
        composite = CompositeAsset(
            id="polyhaven-auto_service",
            source="polyhaven",
            external_id="auto_service",
            name="Auto Service",
            composite_type=CompositeType.HDRI,
            children=[leaf],
        )

        local_tab_plugin = PresenterTestPlugin(
            items=[composite], plugin_id="local", can_download=False
        )
        source_plugin = PresenterTestPlugin(
            items=[], plugin_id="polyhaven", can_download=True
        )

        local_tab_plugin.get_settings_schema = MagicMock(return_value=None)  # type: ignore[method-assign]
        source_plugin.get_settings_schema = MagicMock(  # type: ignore[method-assign]
            return_value={
                "resolution": {
                    "type": "choice",
                    "options": ["1k", "2k"],
                    "default": "2k",
                }
            }
        )

        presenter = TabPresenter(
            plugin=local_tab_plugin,
            view=mock_view,
            host=mock_host,
            get_plugin_by_source=lambda source: source_plugin if source == "polyhaven" else None,
        )
        asyncio.run(presenter._do_search(""))

        presenter._show_settings_dialog = MagicMock(  # type: ignore[method-assign]
            return_value={"resolution": "2k"}
        )
        presenter._on_import_requested(composite.id)

        source_plugin.get_settings_schema.assert_called_once_with(composite)
        presenter._show_settings_dialog.assert_called_once()
        assert len(mock_host.imported_composites) == 1
        _imported, options = mock_host.imported_composites[0]
        assert options["resolution"] == "2k"
        assert options["renderer"] == "arnold"

    def test_download_asset_delegates_to_source_plugin(
        self, mock_view: MagicMock, mock_host: MockHostIntegration, tmp_path: Path
    ) -> None:
        from uab.presenters.tab_presenter import TabPresenter

        asset = Asset(
            id="polyhaven-rusty_metal:diffuse:2k",
            source="polyhaven",
            external_id="rusty_metal:diffuse:2k",
            name="rusty_diff_2k.png",
            asset_type=AssetType.TEXTURE,
            status=AssetStatus.CLOUD,
            remote_url="https://example.com/rusty_diff_2k.png",
            metadata={"resolution": "2k", "map_type": "diffuse"},
        )
        updated = Asset.from_dict(
            {
                **asset.to_dict(),
                "status": AssetStatus.LOCAL.value,
                "local_path": str(tmp_path / "rusty_diff_2k.png"),
            }
        )

        local_tab_plugin = PresenterTestPlugin(
            items=[asset], plugin_id="local", can_download=False
        )
        source_plugin = PresenterTestPlugin(
            items=[], plugin_id="polyhaven", can_download=True
        )
        source_plugin.download_asset_mock.return_value = updated

        resolver = lambda source: source_plugin if source == "polyhaven" else None

        presenter = TabPresenter(
            plugin=local_tab_plugin,
            view=mock_view,
            host=mock_host,
            get_plugin_by_source=resolver,
        )
        asyncio.run(presenter._do_search(""))

        payloads: list[object] = []
        presenter.download_complete.connect(lambda p: payloads.append(p))

        presenter._on_download_asset_requested(asset.id)

        local_tab_plugin.download_asset_mock.assert_not_awaited()
        source_plugin.download_asset_mock.assert_awaited_once()
        assert payloads and isinstance(payloads[-1], dict)
        assert payloads[-1]["source"] == "polyhaven"
        assert asset.id in payloads[-1]["downloaded_item_ids"]

    def test_download_asset_without_source_plugin_emits_unavailable_message(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        from uab.presenters.tab_presenter import TabPresenter

        asset = Asset(
            id="unknown-item",
            source="unknown_source",
            external_id="unknown:item",
            name="unknown.png",
            asset_type=AssetType.TEXTURE,
            status=AssetStatus.CLOUD,
            remote_url="https://example.com/unknown.png",
            metadata={},
        )

        local_tab_plugin = PresenterTestPlugin(
            items=[asset], plugin_id="local", can_download=False
        )

        presenter = TabPresenter(
            plugin=local_tab_plugin,
            view=mock_view,
            host=mock_host,
            get_plugin_by_source=lambda source: None,
        )
        asyncio.run(presenter._do_search(""))

        messages: list[str] = []
        presenter.status_message.connect(lambda m: messages.append(m))

        presenter._on_download_asset_requested(asset.id)

        local_tab_plugin.download_asset_mock.assert_not_awaited()
        assert messages and "Download is not available for source 'unknown_source'." in messages[-1]
