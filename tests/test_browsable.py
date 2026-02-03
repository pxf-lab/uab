from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from uab.core.interfaces import Browsable
from uab.core.models import AssetStatus


@dataclass
class Asset:
    id: str
    name: str
    source: str
    thumbnail_url: str | None = None
    thumbnail_path: Path | None = None
    status: AssetStatus = AssetStatus.CLOUD

    @property
    def display_status(self) -> AssetStatus:
        return self.status


@dataclass
class CompositeAsset:
    id: str
    name: str
    source: str
    thumbnail_url: str | None = None
    thumbnail_path: Path | None = None
    derived_status: AssetStatus = AssetStatus.CLOUD

    @property
    def display_status(self) -> AssetStatus:
        return self.derived_status


def test_browsable_runtime_check_works_for_asset_and_composite() -> None:
    asset = Asset(id="asset-1", name="Asset", source="test")
    composite = CompositeAsset(
        id="composite-1", name="Composite", source="test")

    assert isinstance(asset, Browsable)
    assert isinstance(composite, Browsable)
