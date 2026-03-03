"""Tests for composite import flow helpers (Milestone 8)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from uab.core.interfaces import RenderStrategy
from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
    StandardAsset,
)
from uab.integrations.houdini.integration import HoudiniIntegration
from uab.integrations.houdini.strategies.arnold import ArnoldStrategy
from uab.integrations.houdini.strategies.karma import KarmaStrategy
from uab.integrations.houdini.strategies.redshift import RedshiftStrategy


class DummyStrategy(RenderStrategy):
    """RenderStrategy stub for testing import traversal."""

    def __init__(
        self,
        *,
        required: set[str] | None = None,
        optional: set[str] | None = None,
    ) -> None:
        self._required = required or set()
        self._optional = optional or set()
        self.material_calls: list[tuple[str, dict[str, Path], dict[str, Any]]] = []

    def get_required_texture_maps(self) -> set[str]:
        return set(self._required)

    def get_optional_texture_maps(self) -> set[str]:
        return set(self._optional)

    def create_environment_light(
        self, composite: CompositeAsset, options: dict[str, Any]
    ) -> Any:
        raise NotImplementedError

    def update_environment_light(
        self, asset: StandardAsset, options: dict[str, Any]
    ) -> None:
        return None

    def create_material_from_textures(
        self, name: str, textures: dict[str, Path], options: dict[str, Any]
    ) -> Any:
        self.material_calls.append((name, dict(textures), dict(options)))
        return {"name": name, "textures": textures}

    def create_material(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        raise NotImplementedError

    def update_material(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        return None


class DummyHdriStrategy(RenderStrategy):
    """RenderStrategy stub for testing HDRI composite handoff."""

    def __init__(self) -> None:
        self.hdri_calls: list[tuple[CompositeAsset, dict[str, Any]]] = []

    def get_required_texture_maps(self) -> set[str]:
        return set()

    def get_optional_texture_maps(self) -> set[str]:
        return set()

    def create_environment_light(
        self, composite: CompositeAsset, options: dict[str, Any]
    ) -> Any:
        self.hdri_calls.append((composite, dict(options)))
        return {"name": composite.name, "count": len(composite.children)}

    def update_environment_light(
        self, asset: StandardAsset, options: dict[str, Any]
    ) -> None:
        return None

    def create_material_from_textures(
        self, name: str, textures: dict[str, Path], options: dict[str, Any]
    ) -> Any:
        raise NotImplementedError

    def create_material(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        raise NotImplementedError

    def update_material(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        return None


class _FakeHouUI:
    """Small fake for hou.ui.selectFromList in integration tests."""

    def __init__(self, selection: tuple[int, ...] | tuple[()]) -> None:
        self.selection = selection

    def selectFromList(self, *_args, **_kwargs) -> tuple[int, ...] | tuple[()]:
        return self.selection


class _FakeHou:
    def __init__(self, selection: tuple[int, ...] | tuple[()]) -> None:
        self.ui = _FakeHouUI(selection)


def _make_asset(
    path: Path,
    *,
    asset_type: AssetType = AssetType.TEXTURE,
    resolution: str | None = None,
    status: AssetStatus = AssetStatus.LOCAL,
) -> Asset:
    if status == AssetStatus.LOCAL:
        path.write_bytes(b"data")

    meta: dict[str, Any] = {}
    if resolution is not None:
        meta["resolution"] = resolution

    return Asset(
        id=f"{asset_type.value}:{path.name}",
        source="test",
        external_id=path.name,
        name=path.name,
        asset_type=asset_type,
        status=status,
        local_path=path if status == AssetStatus.LOCAL else None,
        remote_url=None,
        thumbnail_url=None,
        thumbnail_path=None,
        file_size=None,
        metadata=meta,
    )


def _texture(role: str, children: list[Asset]) -> CompositeAsset:
    return CompositeAsset(
        id=f"tex:{role}",
        source="test",
        external_id=f"tex:{role}",
        name=role,
        composite_type=CompositeType.TEXTURE,
        metadata={"role": role},
        children=children,
    )


def _material(name: str, children: list[CompositeAsset]) -> CompositeAsset:
    return CompositeAsset(
        id=f"mat:{name}",
        source="test",
        external_id=f"mat:{name}",
        name=name,
        composite_type=CompositeType.MATERIAL,
        metadata={},
        children=children,
    )


def _hdri(name: str, children: list[Asset]) -> CompositeAsset:
    return CompositeAsset(
        id=f"hdri:{name}",
        source="test",
        external_id=f"hdri:{name}",
        name=name,
        composite_type=CompositeType.HDRI,
        metadata={},
        children=children,
    )


def test_get_asset_for_resolution_returns_exact_match(tmp_path: Path) -> None:
    integration = HoudiniIntegration()

    a1k = _make_asset(tmp_path / "diffuse_1k.png", resolution="1k")
    a2k = _make_asset(tmp_path / "diffuse_2k.png", resolution="2k")
    a4k = _make_asset(tmp_path / "diffuse_4k.png", resolution="4k")

    comp = _texture("diffuse", [a1k, a2k, a4k])
    selected = integration._get_asset_for_resolution(comp, "2k")

    assert selected is not None
    assert selected.id == a2k.id


def test_get_asset_for_resolution_falls_back_to_best_local(tmp_path: Path) -> None:
    integration = HoudiniIntegration()

    a2k_cloud = _make_asset(
        tmp_path / "diffuse_2k.png", resolution="2k", status=AssetStatus.CLOUD
    )
    a4k_local = _make_asset(tmp_path / "diffuse_4k.png", resolution="4k")

    comp = _texture("diffuse", [a2k_cloud, a4k_local])
    selected = integration._get_asset_for_resolution(comp, "2k")

    assert selected is not None
    assert selected.id == a4k_local.id


def test_get_asset_for_resolution_without_target_returns_highest(tmp_path: Path) -> None:
    integration = HoudiniIntegration()

    a1k = _make_asset(tmp_path / "diffuse_1k.png", resolution="1k")
    a4k = _make_asset(tmp_path / "diffuse_4k.png", resolution="4k")

    comp = _texture("diffuse", [a1k, a4k])
    selected = integration._get_asset_for_resolution(comp, None)

    assert selected is not None
    assert selected.id == a4k.id


def test_get_asset_for_resolution_returns_none_when_no_local(tmp_path: Path) -> None:
    integration = HoudiniIntegration()

    a2k_cloud = _make_asset(
        tmp_path / "diffuse_2k.png", resolution="2k", status=AssetStatus.CLOUD
    )
    comp = _texture("diffuse", [a2k_cloud])

    assert integration._get_asset_for_resolution(comp, "2k") is None


def test_get_hdri_asset_for_preferences_prefers_requested_format_at_exact_resolution(
    tmp_path: Path,
) -> None:
    integration = HoudiniIntegration()

    hdr_2k = _make_asset(
        tmp_path / "sunset_2k.hdr",
        asset_type=AssetType.HDRI,
        resolution="2k",
    )
    hdr_2k.metadata["format"] = "hdr"

    exr_2k = _make_asset(
        tmp_path / "sunset_2k.exr",
        asset_type=AssetType.HDRI,
        resolution="2k",
    )
    exr_2k.metadata["format"] = "exr"

    hdri = CompositeAsset(
        id="hdri:sunset",
        source="test",
        external_id="sunset",
        name="sunset",
        composite_type=CompositeType.HDRI,
        children=[hdr_2k, exr_2k],
    )

    selected = integration._get_hdri_asset_for_preferences(
        hdri,
        target_resolution="2k",
        preferred_format="exr",
    )
    assert selected is not None
    assert selected.id == exr_2k.id


def test_get_hdri_asset_for_preferences_fallback_order(tmp_path: Path) -> None:
    integration = HoudiniIntegration()

    hdr_2k = _make_asset(
        tmp_path / "sunset_2k.hdr",
        asset_type=AssetType.HDRI,
        resolution="2k",
    )
    hdr_2k.metadata["format"] = "hdr"

    exr_4k = _make_asset(
        tmp_path / "sunset_4k.exr",
        asset_type=AssetType.HDRI,
        resolution="4k",
    )
    exr_4k.metadata["format"] = "exr"

    hdri = CompositeAsset(
        id="hdri:sunset",
        source="test",
        external_id="sunset",
        name="sunset",
        composite_type=CompositeType.HDRI,
        children=[hdr_2k, exr_4k],
    )

    # Exact resolution should win over preferred format.
    selected_exact = integration._get_hdri_asset_for_preferences(
        hdri,
        target_resolution="2k",
        preferred_format="exr",
    )
    assert selected_exact is not None
    assert selected_exact.id == hdr_2k.id

    # Without a target resolution, preferred format should win.
    selected_preferred = integration._get_hdri_asset_for_preferences(
        hdri,
        target_resolution=None,
        preferred_format="exr",
    )
    assert selected_preferred is not None
    assert selected_preferred.id == exr_4k.id


def test_import_material_uses_requested_resolution(tmp_path: Path) -> None:
    integration = HoudiniIntegration()
    dummy = DummyStrategy(required={"diffuse", "base_color", "albedo"})
    integration._strategies = {"karma": dummy}

    diffuse_1k = _make_asset(tmp_path / "diffuse_1k.png", resolution="1k")
    diffuse_2k = _make_asset(tmp_path / "diffuse_2k.png", resolution="2k")
    normal_2k = _make_asset(tmp_path / "normal_2k.png", resolution="2k")

    mat = _material(
        "brick",
        [
            _texture("diffuse", [diffuse_1k, diffuse_2k]),
            _texture("normal", [normal_2k]),
        ],
    )

    result = integration._import_material(
        mat, {"renderer": "karma", "resolution": "2k"}
    )

    assert dummy.material_calls
    _name, textures, _opts = dummy.material_calls[0]
    assert textures["diffuse"] == diffuse_2k.local_path
    assert textures["normal"] == normal_2k.local_path
    assert result["name"] == "brick"


def test_import_texture_composite_treated_as_single_map_material(tmp_path: Path) -> None:
    integration = HoudiniIntegration()
    dummy = DummyStrategy(required={"diffuse", "base_color", "albedo"})
    integration._strategies = {"karma": dummy}

    diffuse_2k = _make_asset(tmp_path / "brick_diffuse_2k.png", resolution="2k")

    # Mimic local plugin external_id convention: "<dir>::<basename>::<map_type>"
    tex = CompositeAsset(
        id="tex:brick:diffuse",
        source="test",
        external_id=f"{tmp_path}::brick::diffuse",
        name="diffuse",
        composite_type=CompositeType.TEXTURE,
        metadata={"map_type": "diffuse"},
        children=[diffuse_2k],
    )

    integration._import_material(tex, {"renderer": "karma", "resolution": "2k"})

    assert dummy.material_calls
    name, textures, _opts = dummy.material_calls[0]
    assert name == "brick"
    assert textures["diffuse"] == diffuse_2k.local_path


def test_import_material_resolution_fallback_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    integration = HoudiniIntegration()
    dummy = DummyStrategy(required={"diffuse", "base_color", "albedo"})
    integration._strategies = {"karma": dummy}

    diffuse_4k = _make_asset(tmp_path / "diffuse_4k.png", resolution="4k")
    mat = _material("brick", [_texture("diffuse", [diffuse_4k])])

    caplog.set_level(logging.WARNING)
    integration._import_material(mat, {"renderer": "karma", "resolution": "2k"})

    assert "Requested resolution 2k" in caplog.text


def test_import_material_missing_required_texture_raises(tmp_path: Path) -> None:
    integration = HoudiniIntegration()
    dummy = DummyStrategy(required={"diffuse", "base_color", "albedo"})
    integration._strategies = {"karma": dummy}

    normal_2k = _make_asset(tmp_path / "normal_2k.png", resolution="2k")
    mat = _material("brick", [_texture("normal", [normal_2k])])

    with pytest.raises(ValueError, match="Missing required texture map"):
        integration._import_material(mat, {"renderer": "karma", "resolution": "2k"})


def test_import_material_missing_optional_texture_logs_info(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    integration = HoudiniIntegration()
    dummy = DummyStrategy(
        required={"diffuse", "base_color", "albedo"},
        optional={"ao"},
    )
    integration._strategies = {"karma": dummy}

    diffuse_2k = _make_asset(tmp_path / "diffuse_2k.png", resolution="2k")
    mat = _material("brick", [_texture("diffuse", [diffuse_2k])])

    caplog.set_level(logging.INFO)
    integration._import_material(mat, {"renderer": "karma", "resolution": "2k"})

    assert "Missing optional textures" in caplog.text


def test_import_hdri_composite_narrows_variants_for_karma_renderer(
    tmp_path: Path,
) -> None:
    integration = HoudiniIntegration()
    strategy = DummyHdriStrategy()
    integration._strategies = {"karma": strategy}

    hdr_2k = _make_asset(
        tmp_path / "sunset_2k.hdr",
        asset_type=AssetType.HDRI,
        resolution="2k",
    )
    hdr_2k.metadata["format"] = "hdr"

    exr_4k = _make_asset(
        tmp_path / "sunset_4k.exr",
        asset_type=AssetType.HDRI,
        resolution="4k",
    )
    exr_4k.metadata["format"] = "exr"

    hdri = _hdri("sunset", [hdr_2k, exr_4k])

    integration._import_hdri_composite(hdri, {"renderer": "karma", "resolution": "2k"})

    assert strategy.hdri_calls
    passed_composite, _passed_options = strategy.hdri_calls[0]
    assert len(passed_composite.children) == 1
    child = passed_composite.children[0]
    assert isinstance(child, Asset)
    assert child.id == hdr_2k.id


def test_import_hdri_composite_narrows_variants_for_non_karma_renderer(
    tmp_path: Path,
) -> None:
    integration = HoudiniIntegration()
    strategy = DummyHdriStrategy()
    integration._strategies = {"redshift": strategy}

    hdr_2k = _make_asset(
        tmp_path / "sunset_2k.hdr",
        asset_type=AssetType.HDRI,
        resolution="2k",
    )
    hdr_2k.metadata["format"] = "hdr"

    exr_4k = _make_asset(
        tmp_path / "sunset_4k.exr",
        asset_type=AssetType.HDRI,
        resolution="4k",
    )
    exr_4k.metadata["format"] = "exr"

    hdri = _hdri("sunset", [hdr_2k, exr_4k])

    integration._import_hdri_composite(
        hdri,
        {"renderer": "redshift", "resolution": "2k"},
    )

    assert strategy.hdri_calls
    passed_composite, _passed_options = strategy.hdri_calls[0]
    assert len(passed_composite.children) == 1
    child = passed_composite.children[0]
    assert isinstance(child, Asset)
    assert child.id == hdr_2k.id


def test_import_hdri_composite_prompt_uses_user_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uab.integrations.houdini.integration as houdini_integration

    integration = HoudiniIntegration()
    strategy = DummyHdriStrategy()
    integration._strategies = {"karma": strategy}

    hdr_2k = _make_asset(
        tmp_path / "sunset_2k.hdr",
        asset_type=AssetType.HDRI,
        resolution="2k",
    )
    hdr_2k.metadata["format"] = "hdr"

    exr_4k = _make_asset(
        tmp_path / "sunset_4k.exr",
        asset_type=AssetType.HDRI,
        resolution="4k",
    )
    exr_4k.metadata["format"] = "exr"

    hdri = _hdri("sunset", [hdr_2k, exr_4k])

    monkeypatch.setattr(houdini_integration, "has_hou", lambda: True)
    monkeypatch.setattr(houdini_integration, "require_hou", lambda: _FakeHou((1,)))

    integration._import_hdri_composite(
        hdri,
        {"renderer": "karma", "resolution": "2k", "prompt_for_hdri_file": True},
    )

    assert strategy.hdri_calls
    passed_composite, _passed_options = strategy.hdri_calls[0]
    assert len(passed_composite.children) == 1
    child = passed_composite.children[0]
    assert isinstance(child, Asset)
    assert child.id == exr_4k.id


def test_normalize_texture_keys_handles_variants(tmp_path: Path) -> None:
    strategy = KarmaStrategy()
    textures = {
        "base_color": tmp_path / "base.exr",
        "nor_dx": tmp_path / "n.exr",
        "rough": tmp_path / "r.exr",
        "metalness": tmp_path / "m.exr",
        "ambient_occlusion": tmp_path / "ao.exr",
    }

    normalized = strategy._normalize_texture_keys(textures)
    assert normalized["diffuse"] == textures["base_color"]
    assert normalized["normal"] == textures["nor_dx"]
    assert normalized["roughness"] == textures["rough"]
    assert normalized["metallic"] == textures["metalness"]
    assert normalized["ao"] == textures["ambient_occlusion"]


@pytest.mark.parametrize(
    "strategy_cls",
    [KarmaStrategy, ArnoldStrategy, RedshiftStrategy],
)
def test_strategies_declare_required_texture_maps(strategy_cls: type) -> None:
    strategy = strategy_cls()
    assert strategy.get_required_texture_maps() == {"diffuse", "base_color", "albedo"}

