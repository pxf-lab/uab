"""Regression tests for PolyHaven expansion status reconciliation.

When expanding a composite from the PolyHaven API, leaf files are reported as
cloud assets. If a file was already downloaded, the expanded leaf `Asset` should
surface as LOCAL so the UI doesn't show everything as CLOUD.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from uab.core.database import AssetDatabase
from uab.core.models import Asset, AssetStatus, CompositeAsset, CompositeType
from uab.plugins.polyhaven import PolyHavenPlugin


@pytest.mark.parametrize(
    "composite,manifest,expected_external_id,remote_url",
    [
        (
            CompositeAsset(
                id="polyhaven-rusty_metal:diffuse",
                source="polyhaven",
                external_id="rusty_metal:diffuse",
                name="diffuse",
                composite_type=CompositeType.TEXTURE,
                metadata={"role": "diffuse", "map_type": "diffuse"},
                children=[],
            ),
            {
                "diffuse": {
                    "2k": {
                        "png": {
                            "url": "https://example.com/rusty_diff_2k.png",
                            "size": 20,
                        }
                    }
                }
            },
            "rusty_metal:diffuse:2k",
            "https://example.com/rusty_diff_2k.png",
        ),
        (
            CompositeAsset(
                id="polyhaven-sunset_hdri",
                source="polyhaven",
                external_id="sunset_hdri",
                name="Sunset HDRI",
                composite_type=CompositeType.HDRI,
                metadata={},
                children=[],
            ),
            {
                "hdri": {
                    "2k": {
                        "hdr": {
                            "url": "https://example.com/sunset_2k.hdr",
                            "size": 20,
                        }
                    }
                }
            },
            "sunset_hdri:2k:hdr",
            "https://example.com/sunset_2k.hdr",
        ),
        (
            CompositeAsset(
                id="polyhaven-simple_chair",
                source="polyhaven",
                external_id="simple_chair",
                name="Simple Chair",
                composite_type=CompositeType.MODEL,
                metadata={},
                children=[],
            ),
            {
                "gltf": {
                    "2k": {
                        "gltf": {
                            "url": "https://example.com/chair_2k.gltf",
                            "size": 20,
                        }
                    }
                }
            },
            "simple_chair:gltf:2k",
            "https://example.com/chair_2k.gltf",
        ),
    ],
)
def test_expand_composite_marks_existing_download_as_local(
    tmp_path: Path,
    composite: CompositeAsset,
    manifest: dict,
    expected_external_id: str,
    remote_url: str,
) -> None:
    db = AssetDatabase(db_path=tmp_path / "test.db")
    plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

    filename = Path(remote_url.split("?", 1)[0]).name
    root_id = expected_external_id.split(":", 1)[0]
    expected_local_path = plugin.library_root / root_id / filename
    expected_local_path.parent.mkdir(parents=True, exist_ok=True)
    expected_local_path.write_bytes(b"data")

    with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = manifest
        expanded = asyncio.run(plugin.expand_composite(composite))

    assert len(expanded.children) == 1
    child = expanded.children[0]
    assert isinstance(child, Asset)
    assert child.external_id == expected_external_id
    assert child.status == AssetStatus.LOCAL
    assert child.local_path == expected_local_path


def test_expand_texture_keeps_cloud_when_file_missing(tmp_path: Path) -> None:
    db = AssetDatabase(db_path=tmp_path / "test.db")
    plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

    texture = CompositeAsset(
        id="polyhaven-rusty_metal:diffuse",
        source="polyhaven",
        external_id="rusty_metal:diffuse",
        name="diffuse",
        composite_type=CompositeType.TEXTURE,
        metadata={"role": "diffuse", "map_type": "diffuse"},
        children=[],
    )

    manifest = {
        "diffuse": {
            "2k": {
                "png": {
                    "url": "https://example.com/rusty_diff_2k.png",
                    "size": 20,
                }
            }
        }
    }

    with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = manifest
        expanded = asyncio.run(plugin.expand_composite(texture))

    assert len(expanded.children) == 1
    child = expanded.children[0]
    assert isinstance(child, Asset)
    assert child.status == AssetStatus.CLOUD
    assert child.local_path is None

