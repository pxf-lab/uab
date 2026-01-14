"""Tests for database layer."""

from pathlib import Path
from typing import Callable

from uab.core.database import AssetDatabase
from uab.core.models import AssetStatus, StandardAsset


def test_upsert_and_fetch_by_external_id(tmp_path: Path, make_asset: Callable[..., StandardAsset]) -> None:
    """The database is always empty when the test starts, so upsert can't be tested
    without fetching anyway."""
    db = AssetDatabase(tmp_path / "assets.db")
    asset = make_asset()

    db.upsert_asset(asset)
    fetched = db.get_asset_by_external_id(asset.source, asset.external_id)

    assert fetched is not None
    assert fetched.source == asset.source
    assert fetched.external_id == asset.external_id
    assert fetched.name == asset.name
    assert fetched.status == asset.status
    assert fetched.metadata == asset.metadata


def test_get_asset_by_id(tmp_path: Path, make_asset: Callable[..., StandardAsset]) -> None:
    db = AssetDatabase(tmp_path / "assets.db")
    asset = make_asset(external_id="wood_001", name="Wood")

    db.upsert_asset(asset)
    fetched = db.get_asset_by_id(asset.id)

    assert fetched is not None
    assert fetched.external_id == asset.external_id
    assert fetched.source == asset.source


def test_get_local_assets_and_search(tmp_path: Path, make_asset: Callable[..., StandardAsset]) -> None:
    db = AssetDatabase(tmp_path / "assets.db")
    a1 = make_asset(external_id="brick_001", name="Brick Wall")
    a2 = make_asset(
        external_id="marble_001",
        name="Marble Floor",
        status=AssetStatus.CLOUD,
    )

    db.upsert_asset(a1)
    db.upsert_asset(a2)

    local_assets = db.get_local_assets()
    assert len(local_assets) == 1
    assert local_assets[0].external_id == "brick_001"

    results = db.search_assets("Brick")
    assert len(results) == 1
    assert results[0].external_id == "brick_001"
