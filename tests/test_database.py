"""Tests for database layer."""

import json
import sqlite3
from pathlib import Path
import pytest

from uab.core.database import AssetDatabase
from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
)


def _make_asset(
    *,
    asset_id: str,
    name: str,
    status: AssetStatus,
    role: str | None = None,
) -> Asset:
    metadata = {}
    if role is not None:
        metadata["role"] = role
    return Asset(
        id=asset_id,
        source="test",
        external_id=asset_id,
        name=name,
        asset_type=AssetType.TEXTURE,
        status=status,
        remote_url="https://example.com/file.png",
        file_size=123,
        metadata=metadata,
    )


def _make_composite(
    *,
    composite_id: str,
    name: str,
    composite_type: CompositeType,
    role: str | None = None,
) -> CompositeAsset:
    metadata = {}
    if role is not None:
        metadata["role"] = role
    return CompositeAsset(
        id=composite_id,
        source="test",
        external_id=composite_id,
        name=name,
        composite_type=composite_type,
        metadata=metadata,
        children=[],
    )


def test_upsert_asset_and_get_asset_roundtrip(tmp_path: Path) -> None:
    db = AssetDatabase(tmp_path / "assets.db")
    asset = _make_asset(
        asset_id="a1", name="Brick Diffuse 2k", status=AssetStatus.CLOUD)

    db.upsert_asset(asset)
    fetched = db.get_asset(asset.id)

    assert fetched is not None
    assert fetched.id == asset.id
    assert fetched.source == asset.source
    assert fetched.external_id == asset.external_id
    assert fetched.name == asset.name
    assert fetched.asset_type == asset.asset_type
    assert fetched.status == asset.status
    assert fetched.remote_url == asset.remote_url
    assert fetched.file_size == asset.file_size
    assert fetched.metadata == asset.metadata


def test_search_assets_by_name(tmp_path: Path) -> None:
    db = AssetDatabase(tmp_path / "assets.db")
    a1 = _make_asset(asset_id="brick_001", name="Brick Wall",
                     status=AssetStatus.LOCAL)
    a2 = _make_asset(asset_id="marble_001",
                     name="Marble Floor", status=AssetStatus.CLOUD)
    db.upsert_asset(a1)
    db.upsert_asset(a2)

    results = db.search_assets("Brick")
    assert [r.id for r in results] == ["brick_001"]


def test_get_local_assets_filters_by_status(tmp_path: Path) -> None:
    db = AssetDatabase(tmp_path / "assets.db")
    a1 = _make_asset(asset_id="brick_001", name="Brick Wall",
                     status=AssetStatus.LOCAL)
    a2 = _make_asset(asset_id="marble_001",
                     name="Marble Floor", status=AssetStatus.CLOUD)
    db.upsert_asset(a1)
    db.upsert_asset(a2)

    local_assets = db.get_local_assets()
    assert [a.id for a in local_assets] == ["brick_001"]


def test_upsert_composite_and_get_composite_roundtrip(tmp_path: Path) -> None:
    db = AssetDatabase(tmp_path / "assets.db")
    comp = CompositeAsset(
        id="c1",
        source="test",
        external_id="c1",
        name="Rock 023",
        composite_type=CompositeType.MATERIAL,
        thumbnail_url="https://example.com/thumb.png",
        thumbnail_path=tmp_path / "thumb.png",
        metadata={"categories": ["rock"]},
        children=[],
    )

    db.upsert_composite(comp)
    fetched = db.get_composite("c1")

    assert fetched is not None
    assert fetched.id == comp.id
    assert fetched.source == comp.source
    assert fetched.external_id == comp.external_id
    assert fetched.name == comp.name
    assert fetched.composite_type == comp.composite_type
    assert fetched.thumbnail_url == comp.thumbnail_url
    assert fetched.thumbnail_path == comp.thumbnail_path
    assert fetched.metadata == comp.metadata
    assert fetched.children == []


def test_set_composite_children_with_asset_children(tmp_path: Path) -> None:
    db = AssetDatabase(tmp_path / "assets.db")
    parent = _make_composite(
        composite_id="mat", name="Material", composite_type=CompositeType.MATERIAL)
    db.upsert_composite(parent)

    diffuse = _make_asset(asset_id="diff", name="Diffuse",
                          status=AssetStatus.CLOUD, role="diffuse")
    normal = _make_asset(asset_id="nor", name="Normal",
                         status=AssetStatus.LOCAL, role="normal")

    db.set_composite_children(parent.id, [diffuse, normal])
    children = db.get_composite_children(parent.id)

    assert [c.id for c in children] == ["diff", "nor"]
    assert all(isinstance(c, Asset) for c in children)
    assert children[0].metadata.get("role") == "diffuse"
    assert children[1].metadata.get("role") == "normal"


def test_set_composite_children_with_composite_children(tmp_path: Path) -> None:
    db = AssetDatabase(tmp_path / "assets.db")
    parent = _make_composite(composite_id="scene",
                             name="Scene", composite_type=CompositeType.SCENE)
    db.upsert_composite(parent)

    child1 = _make_composite(composite_id="mat1", name="Mat 1",
                             composite_type=CompositeType.MATERIAL, role="material_a")
    child2 = _make_composite(composite_id="mat2", name="Mat 2",
                             composite_type=CompositeType.MATERIAL, role="material_b")

    db.set_composite_children(parent.id, [child1, child2])
    children = db.get_composite_children(parent.id)

    assert [c.id for c in children] == ["mat1", "mat2"]
    assert all(isinstance(c, CompositeAsset) for c in children)
    assert children[0].metadata.get("role") == "material_a"
    assert children[1].metadata.get("role") == "material_b"


def test_get_composite_with_children_depth_1(tmp_path: Path) -> None:
    db = AssetDatabase(tmp_path / "assets.db")

    root = _make_composite(composite_id="root", name="Root",
                           composite_type=CompositeType.SCENE)
    mat = _make_composite(composite_id="mat", name="Mat",
                          composite_type=CompositeType.MATERIAL, role="material")
    tex = _make_composite(composite_id="tex", name="Tex",
                          composite_type=CompositeType.TEXTURE, role="diffuse")
    a1 = _make_asset(asset_id="a1", name="1k",
                     status=AssetStatus.CLOUD, role="1k")
    a2 = _make_asset(asset_id="a2", name="2k",
                     status=AssetStatus.LOCAL, role="2k")

    db.upsert_composite(root)
    db.upsert_composite(mat)
    db.upsert_composite(tex)
    db.set_composite_children(tex.id, [a1, a2])
    db.set_composite_children(mat.id, [tex])
    db.set_composite_children(root.id, [mat])

    loaded = db.get_composite_with_children(root.id, depth=1)
    assert loaded is not None
    assert len(loaded.children) == 1
    assert isinstance(loaded.children[0], CompositeAsset)
    assert loaded.children[0].children == []  # depth=1: no recursion


def test_get_composite_with_children_unlimited_depth(tmp_path: Path) -> None:
    db = AssetDatabase(tmp_path / "assets.db")

    root = _make_composite(composite_id="root", name="Root",
                           composite_type=CompositeType.SCENE)
    mat = _make_composite(composite_id="mat", name="Mat",
                          composite_type=CompositeType.MATERIAL, role="material")
    tex = _make_composite(composite_id="tex", name="Tex",
                          composite_type=CompositeType.TEXTURE, role="diffuse")
    a1 = _make_asset(asset_id="a1", name="1k",
                     status=AssetStatus.CLOUD, role="1k")
    a2 = _make_asset(asset_id="a2", name="2k",
                     status=AssetStatus.LOCAL, role="2k")

    db.upsert_composite(root)
    db.upsert_composite(mat)
    db.upsert_composite(tex)
    db.set_composite_children(tex.id, [a1, a2])
    db.set_composite_children(mat.id, [tex])
    db.set_composite_children(root.id, [mat])

    loaded = db.get_composite_with_children(root.id, depth=-1)
    assert loaded is not None

    mat_loaded = loaded.children[0]
    assert isinstance(mat_loaded, CompositeAsset)
    assert len(mat_loaded.children) == 1

    tex_loaded = mat_loaded.children[0]
    assert isinstance(tex_loaded, CompositeAsset)
    assert [a.id for a in tex_loaded.get_all_assets()] == ["a1", "a2"]


def test_cascading_delete_removes_children_rows(tmp_path: Path) -> None:
    db = AssetDatabase(tmp_path / "assets.db")
    parent = _make_composite(composite_id="parent",
                             name="Parent", composite_type=CompositeType.SCENE)
    db.upsert_composite(parent)

    child = _make_asset(asset_id="child", name="Child",
                        status=AssetStatus.LOCAL, role="child")
    db.set_composite_children(parent.id, [child])

    assert len(db.get_composite_children(parent.id)) == 1
    assert db.delete_composite(parent.id) is True

    with db._connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM composite_children WHERE parent_composite_id = ?",
            (parent.id,),
        ).fetchone()
        assert row["n"] == 0


def test_foreign_key_constraints_prevent_orphans(tmp_path: Path) -> None:
    db = AssetDatabase(tmp_path / "assets.db")
    with db._connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO composite_children (parent_composite_id, child_asset_id, role, sort_order)
                VALUES ('missing_parent', 'missing_asset', 'x', 0)
                """
            )


def test_composite_tree_view_returns_child_types_and_statuses(tmp_path: Path) -> None:
    db = AssetDatabase(tmp_path / "assets.db")
    parent = _make_composite(composite_id="parent",
                             name="Parent", composite_type=CompositeType.SCENE)
    child_asset = _make_asset(
        asset_id="asset1", name="Leaf", status=AssetStatus.LOCAL, role="leaf")
    child_comp = _make_composite(composite_id="child_comp", name="ChildComp",
                                 composite_type=CompositeType.MATERIAL, role="child")

    db.upsert_composite(parent)
    db.upsert_composite(child_comp)
    db.set_composite_children(parent.id, [child_asset, child_comp])

    with db._connect() as conn:
        rows = list(conn.execute(
            "SELECT * FROM composite_tree WHERE parent_composite_id = ? ORDER BY sort_order", (parent.id,)))

    assert len(rows) == 2
    assert rows[0]["child_type"] == "asset"
    assert rows[0]["child_id"] == "asset1"
    assert rows[0]["status"] == AssetStatus.LOCAL.value
    assert rows[1]["child_type"] == "composite"
    assert rows[1]["child_id"] == "child_comp"
    assert rows[1]["status"] == "composite"


def _create_v1_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            status TEXT NOT NULL,
            local_path TEXT,
            thumbnail_url TEXT,
            thumbnail_path TEXT,
            metadata TEXT,
            UNIQUE(source, external_id)
        );

        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );
        DELETE FROM schema_version;
        INSERT INTO schema_version (version) VALUES (1);
        """
    )


def test_migrate_empty_v1_database(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_v1_schema(conn)
    conn.commit()
    conn.close()

    db = AssetDatabase(db_path)
    with db._connect() as conn2:
        cols = {r["name"] for r in conn2.execute("PRAGMA table_info(assets)")}
        assert "asset_type" in cols
        assert "remote_url" in cols
        assert "file_size" in cols
        version = conn2.execute(
            "SELECT MAX(version) AS v FROM schema_version").fetchone()["v"]
        assert version == 3


def test_migrate_v1_database_with_existing_data(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_with_data.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_v1_schema(conn)
    conn.execute(
        """
        INSERT INTO assets (id, source, external_id, name, type, status, local_path, thumbnail_url, thumbnail_path, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-1",
            "polyhaven",
            "brick_001",
            "Brick",
            "texture",
            "local",
            "/tmp/brick",
            "https://example.com/thumb.jpg",
            None,
            '{"files": {"diffuse": "brick.png"}}',
        ),
    )
    conn.commit()
    conn.close()

    db = AssetDatabase(db_path)
    asset = db.get_asset("legacy-1")
    assert asset is not None
    assert asset.asset_type == AssetType.TEXTURE
    assert asset.status == AssetStatus.LOCAL

    # Backup table should exist.
    with db._connect() as conn2:
        row = conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='assets_backup_v1'"
        ).fetchone()
        assert row is not None


def test_migrate_v1_database_with_variants_creates_composite_and_leaf_assets(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy_variants.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_v1_schema(conn)

    file_2k = tmp_path / "rusty_diff_2k.png"
    file_2k.write_bytes(b"data")

    conn.execute(
        """
        INSERT INTO assets (id, source, external_id, name, type, status, local_path, thumbnail_url, thumbnail_path, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-tex",
            "polyhaven",
            "rusty_metal:diffuse",
            "Rusty Diffuse",
            "texture",
            "local",
            str(file_2k),
            None,
            None,
            json.dumps(
                {
                    "map_type": "diffuse",
                    "resolution": "2k",
                    "variants": [
                        {
                            "key": "1k",
                            "status": "cloud",
                            "remote_url": "https://example.com/rusty_diff_1k.png",
                        },
                        {
                            "key": "2k",
                            "status": "local",
                            "local_path": str(file_2k),
                            "remote_url": "https://example.com/rusty_diff_2k.png",
                        },
                    ],
                }
            ),
        ),
    )
    conn.commit()
    conn.close()

    db = AssetDatabase(db_path)

    # Composite root created.
    comp = db.get_composite("legacy-tex")
    assert comp is not None
    assert comp.composite_type == CompositeType.TEXTURE
    assert comp.external_id == "rusty_metal:diffuse"

    loaded = db.get_composite_with_children("legacy-tex", depth=1)
    assert loaded is not None
    assert [getattr(c, "metadata", {}).get("role") for c in loaded.children] == [
        "1k",
        "2k",
    ]

    # Root asset row rewritten as base variant.
    base = db.get_asset("legacy-tex")
    assert base is not None
    assert base.external_id == "rusty_metal:diffuse:2k"
    assert base.metadata.get("resolution") == "2k"

    # Other variant exists as a new asset row.
    v1 = db.get_asset("legacy-tex:1k")
    assert v1 is not None
    assert v1.external_id == "rusty_metal:diffuse:1k"
    assert v1.metadata.get("resolution") == "1k"

    # The legacy root external_id should no longer exist as an asset entry.
    assert db.get_asset_by_external_id("polyhaven", "rusty_metal:diffuse") is None


def _create_v2_schema_with_composites(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            status TEXT NOT NULL,
            local_path TEXT,
            thumbnail_url TEXT,
            thumbnail_path TEXT,
            metadata TEXT,
            UNIQUE(source, external_id)
        );

        CREATE TABLE IF NOT EXISTS composites (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            thumbnail_url TEXT,
            thumbnail_path TEXT,
            metadata TEXT,
            UNIQUE(source, external_id)
        );

        CREATE TABLE IF NOT EXISTS composite_members (
            composite_id TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            role TEXT,
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );
        DELETE FROM schema_version;
        INSERT INTO schema_version (version) VALUES (2);
        """
    )


def test_migrate_legacy_composite_members_to_composite_children(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_composites.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_v2_schema_with_composites(conn)

    conn.execute(
        """
        INSERT INTO composites (id, source, external_id, name, type, thumbnail_url, thumbnail_path, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("c1", "polyhaven", "rusty_metal", "Rusty Metal", "material", None, None, "{}"),
    )
    conn.execute(
        """
        INSERT INTO assets (id, source, external_id, name, type, status, local_path, thumbnail_url, thumbnail_path, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("a1", "polyhaven", "rusty_metal:diffuse", "diffuse", "texture", "local", None, None, None, "{}"),
    )
    conn.execute(
        """
        INSERT INTO assets (id, source, external_id, name, type, status, local_path, thumbnail_url, thumbnail_path, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("a2", "polyhaven", "rusty_metal:normal", "normal", "texture", "cloud", None, None, None, "{}"),
    )
    conn.execute(
        """
        INSERT INTO composite_members (composite_id, asset_id, role, sort_order)
        VALUES (?, ?, ?, ?)
        """,
        ("c1", "a1", "diffuse", 0),
    )
    conn.execute(
        """
        INSERT INTO composite_members (composite_id, asset_id, role, sort_order)
        VALUES (?, ?, ?, ?)
        """,
        ("c1", "a2", "normal", 1),
    )
    conn.commit()
    conn.close()

    db = AssetDatabase(db_path)

    # legacy table should have been backed up + dropped.
    with db._connect() as conn2:
        row = conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='composite_members'"
        ).fetchone()
        assert row is None
        backup = conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='composite_members_backup_v2'"
        ).fetchone()
        assert backup is not None

    loaded = db.get_composite_with_children("c1", depth=1)
    assert loaded is not None
    assert loaded.composite_type == CompositeType.MATERIAL
    assert [c.id for c in loaded.children] == ["a1", "a2"]
    assert [c.metadata.get("role") for c in loaded.children] == ["diffuse", "normal"]
