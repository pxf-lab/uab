from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

from uab.core.models import Asset, AssetStatus, AssetType, CompositeAsset, CompositeType


def _ensure_maya_not_imported() -> None:
    assert "maya" not in sys.modules
    assert "maya.cmds" not in sys.modules
    assert "maya.OpenMayaUI" not in sys.modules


def test_maya_integration_module_import_does_not_import_maya() -> None:
    # Ensure a clean slate for this process
    for key in ("maya", "maya.cmds", "maya.OpenMayaUI"):
        sys.modules.pop(key, None)

    _ensure_maya_not_imported()

    importlib.import_module("uab.integrations.maya.integration")

    _ensure_maya_not_imported()


def test_integrations_lazy_attr_exposes_maya_integration_without_importing_maya() -> None:
    for key in ("maya", "maya.cmds", "maya.OpenMayaUI"):
        sys.modules.pop(key, None)

    _ensure_maya_not_imported()

    import uab.integrations as integrations

    MayaIntegration = integrations.MayaIntegration
    assert MayaIntegration.__name__ == "MayaIntegration"

    _ensure_maya_not_imported()


def test_maya_strategy_helpers_normalize_and_select_resolution(tmp_path: Path) -> None:
    """Pure helper coverage: no Maya required."""

    from uab.integrations.maya.strategies.base import SharedMayaRenderStrategyUtils

    class DummyStrategy(SharedMayaRenderStrategyUtils):
        @property
        def renderer_name(self) -> str:
            return "dummy"

        def get_required_texture_maps(self) -> set[str]:
            return set()

        def create_environment_light(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:  # noqa: ANN401
            raise NotImplementedError

        def update_environment_light(self, asset, options: dict[str, Any]) -> None:  # noqa: ANN001
            raise NotImplementedError

        def create_material_from_textures(
            self, name: str, textures: dict[str, Path], options: dict[str, Any]
        ) -> Any:  # noqa: ANN401
            raise NotImplementedError

        def update_material(self, asset, options: dict[str, Any]) -> None:  # noqa: ANN001
            raise NotImplementedError

    strategy = DummyStrategy()

    normalized = strategy._normalize_texture_keys(
        {
            "base_color": tmp_path / "base.png",
            "nor_dx": tmp_path / "n.png",
            "rough": tmp_path / "r.png",
            "metalness": tmp_path / "m.png",
            "ambient_occlusion": tmp_path / "ao.png",
        }
    )
    assert normalized["diffuse"].name == "base.png"
    assert normalized["normal"].name == "n.png"
    assert normalized["roughness"].name == "r.png"
    assert normalized["metallic"].name == "m.png"
    assert normalized["ao"].name == "ao.png"

    # Resolution selection
    a1k = Asset(
        id="a1k",
        source="test",
        external_id="a1k",
        name="diffuse_1k.png",
        asset_type=AssetType.TEXTURE,
        status=AssetStatus.LOCAL,
        local_path=tmp_path / "diffuse_1k.png",
        metadata={"resolution": "1k"},
    )
    a4k = Asset(
        id="a4k",
        source="test",
        external_id="a4k",
        name="diffuse_4k.png",
        asset_type=AssetType.TEXTURE,
        status=AssetStatus.LOCAL,
        local_path=tmp_path / "diffuse_4k.png",
        metadata={"resolution": "4k"},
    )
    a2k_cloud = Asset(
        id="a2k_cloud",
        source="test",
        external_id="a2k_cloud",
        name="diffuse_2k.png",
        asset_type=AssetType.TEXTURE,
        status=AssetStatus.CLOUD,
        local_path=None,
        metadata={"resolution": "2k"},
    )

    comp = CompositeAsset(
        id="tex:diffuse",
        source="test",
        external_id="tex:diffuse",
        name="diffuse",
        composite_type=CompositeType.TEXTURE,
        metadata={"role": "diffuse"},
        children=[a1k, a4k, a2k_cloud],
    )

    selected = strategy._select_local_asset_for_resolution(comp, "2k")
    assert selected is not None
    assert selected.id == "a4k"


def test_maya_integration_selects_hdri_by_resolution_then_format(tmp_path: Path) -> None:
    """HDRI selection should honor requested format with deterministic fallbacks."""
    from uab.integrations.maya.integration import MayaIntegration

    integration = MayaIntegration()

    hdr_2k = Asset(
        id="hdr2k",
        source="test",
        external_id="sunset:2k:hdr",
        name="sunset_2k.hdr",
        asset_type=AssetType.HDRI,
        status=AssetStatus.LOCAL,
        local_path=tmp_path / "sunset_2k.hdr",
        metadata={"resolution": "2k", "format": "hdr"},
    )
    exr_2k = Asset(
        id="exr2k",
        source="test",
        external_id="sunset:2k:exr",
        name="sunset_2k.exr",
        asset_type=AssetType.HDRI,
        status=AssetStatus.LOCAL,
        local_path=tmp_path / "sunset_2k.exr",
        metadata={"resolution": "2k", "format": "exr"},
    )
    exr_4k = Asset(
        id="exr4k",
        source="test",
        external_id="sunset:4k:exr",
        name="sunset_4k.exr",
        asset_type=AssetType.HDRI,
        status=AssetStatus.LOCAL,
        local_path=tmp_path / "sunset_4k.exr",
        metadata={"resolution": "4k", "format": "exr"},
    )

    hdri = CompositeAsset(
        id="hdri:sunset",
        source="test",
        external_id="sunset",
        name="Sunset",
        composite_type=CompositeType.HDRI,
        children=[hdr_2k, exr_2k, exr_4k],
    )

    # Exact resolution + preferred format.
    selected = integration._get_hdri_asset_for_preferences(
        hdri,
        target_resolution="2k",
        preferred_format="exr",
    )
    assert selected is not None
    assert selected.id == "exr2k"

    # Exact resolution should beat preferred format at a different resolution.
    selected_exact_any = integration._get_hdri_asset_for_preferences(
        hdri,
        target_resolution="2k",
        preferred_format="hdr",
    )
    assert selected_exact_any is not None
    assert selected_exact_any.id == "hdr2k"

