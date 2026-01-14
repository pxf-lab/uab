"""Tests for database layer."""

from pathlib import Path
from typing import Callable

from uab.core.database import AssetDatabase
from uab.core.models import StandardAsset


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
