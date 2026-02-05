"""SQLite database for asset persistence with file locking."""

import fcntl
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    Composable,
    CompositeAsset,
    CompositeType,
    StandardAsset,
)
from uab.core import config

# Schema version for future migrations
SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    status TEXT NOT NULL,
    local_path TEXT,
    remote_url TEXT,
    thumbnail_url TEXT,
    thumbnail_path TEXT,
    file_size INTEGER,
    metadata TEXT,
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_assets_source ON assets(source);
CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);

CREATE TABLE IF NOT EXISTS composites (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    composite_type TEXT NOT NULL,
    thumbnail_url TEXT,
    thumbnail_path TEXT,
    metadata TEXT,
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_composites_source ON composites(source);
CREATE INDEX IF NOT EXISTS idx_composites_type ON composites(composite_type);

CREATE TABLE IF NOT EXISTS composite_children (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_composite_id TEXT NOT NULL,
    child_asset_id TEXT,
    child_composite_id TEXT,
    role TEXT,
    sort_order INTEGER DEFAULT 0,

    FOREIGN KEY (parent_composite_id) REFERENCES composites(id) ON DELETE CASCADE,
    FOREIGN KEY (child_asset_id) REFERENCES assets(id) ON DELETE CASCADE,
    FOREIGN KEY (child_composite_id) REFERENCES composites(id) ON DELETE CASCADE,

    CHECK (
        (child_asset_id IS NOT NULL AND child_composite_id IS NULL) OR
        (child_asset_id IS NULL AND child_composite_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_composite_children_parent ON composite_children(parent_composite_id);
CREATE INDEX IF NOT EXISTS idx_composite_children_asset ON composite_children(child_asset_id);
CREATE INDEX IF NOT EXISTS idx_composite_children_composite ON composite_children(child_composite_id);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE VIEW IF NOT EXISTS composite_tree AS
SELECT 
    cc.parent_composite_id,
    cc.role,
    cc.sort_order,
    CASE 
        WHEN cc.child_asset_id IS NOT NULL THEN 'asset'
        ELSE 'composite'
    END AS child_type,
    COALESCE(cc.child_asset_id, cc.child_composite_id) AS child_id,
    COALESCE(a.name, c.name) AS child_name,
    COALESCE(a.status, 'composite') AS status
FROM composite_children cc
LEFT JOIN assets a ON cc.child_asset_id = a.id
LEFT JOIN composites c ON cc.child_composite_id = c.id
ORDER BY cc.parent_composite_id, cc.sort_order;
"""


def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """Return the set of column names for a table (empty if missing)."""
    try:
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
    except sqlite3.OperationalError:
        return set()
    return {row["name"] for row in cursor}


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _get_schema_version(conn: sqlite3.Connection) -> int | None:
    """Get current schema version (None if missing)."""
    try:
        row = conn.execute(
            "SELECT MAX(version) AS version FROM schema_version"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row or row["version"] is None:
        return None
    return int(row["version"])


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))


def _decode_metadata_payload(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _encode_metadata_payload(meta: dict[str, Any] | None) -> str | None:
    if not meta:
        return None
    try:
        return json.dumps(meta)
    except TypeError:
        # Non-serializable metadata should not block migration; drop it.
        return None


def _extract_variants(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize legacy metadata['variants'] into a list of dict entries."""
    variants_any = meta.get("variants")
    if not variants_any:
        return []

    if isinstance(variants_any, list):
        return [v for v in variants_any if isinstance(v, dict)]

    if isinstance(variants_any, dict):
        out: list[dict[str, Any]] = []
        for k, v_any in variants_any.items():
            if not isinstance(v_any, dict):
                continue
            entry = dict(v_any)
            entry.setdefault("key", str(k))
            out.append(entry)
        return out

    return []


def _infer_variant_key_from_path(path_value: str | None) -> str | None:
    if not path_value:
        return None
    m = re.search(r"(?i)(?P<res>\d+\s*k)\b", str(path_value))
    if not m:
        return None
    return m.group("res").replace(" ", "").lower()


def _resolution_sort_key(value: str) -> int:
    m = re.match(r"(?i)^(?P<num>\d+)\s*k$", value.strip())
    if not m:
        return 0
    try:
        return int(m.group("num"))
    except ValueError:
        return 0


def _asset_type_to_composite_type(asset_type_value: str) -> CompositeType:
    """Map legacy AssetType string to a leaf CompositeType."""
    try:
        at = AssetType(asset_type_value)
    except Exception:
        return CompositeType.TEXTURE

    if at == AssetType.HDRI:
        return CompositeType.HDRI
    if at == AssetType.MODEL:
        return CompositeType.MODEL
    return CompositeType.TEXTURE


def _migrate_assets_with_variants(conn: sqlite3.Connection) -> None:
    """Convert legacy StandardAsset rows with metadata.variants into composites + leaf assets."""
    assets_cols = _get_table_columns(conn, "assets")
    type_col = "asset_type" if "asset_type" in assets_cols else "type"

    # Ensure required v3 columns exist before start!
    if "remote_url" not in assets_cols:
        conn.execute("ALTER TABLE assets ADD COLUMN remote_url TEXT")
    if "file_size" not in assets_cols:
        conn.execute("ALTER TABLE assets ADD COLUMN file_size INTEGER")

    query = f"""
        SELECT
            id, source, external_id, name,
            {type_col} AS type_value,
            status, local_path, remote_url,
            thumbnail_url, thumbnail_path, file_size,
            metadata
        FROM assets
    """

    rows = list(conn.execute(query))
    for row in rows:
        meta = _decode_metadata_payload(row["metadata"])
        variants = _extract_variants(meta)
        if not variants:
            continue

        # Best-effort: infer which variant the root asset row currently represents.
        root_local_path = row["local_path"]
        root_remote_url = row["remote_url"]

        base_key_any = None
        if isinstance(meta.get("resolution"), str):
            base_key_any = meta.get("resolution")
        if not base_key_any:
            base_key_any = _infer_variant_key_from_path(
                root_local_path or row["external_id"])

        # Normalize variants into a dict keyed by string key.
        by_key: dict[str, dict[str, Any]] = {}
        for v in variants:
            key_any = v.get("key") or v.get("resolution") or v.get("name")
            if not isinstance(key_any, str):
                continue
            key = key_any.strip()
            if not key:
                continue
            key = key.replace(" ", "").lower()
            by_key[key] = {**v, "key": key}

        if not by_key:
            meta.pop("variants", None)
            conn.execute(
                "UPDATE assets SET metadata = ? WHERE id = ?",
                (_encode_metadata_payload(meta), row["id"]),
            )
            continue

        base_key = (
            str(base_key_any).strip().replace(" ", "").lower()
            if isinstance(base_key_any, str) and base_key_any.strip()
            else sorted(by_key.keys())[0]
        )

        # Ensure base entry exists; if variant ommits, get from rot
        if base_key not in by_key:
            by_key[base_key] = {
                "key": base_key,
                "status": row["status"],
                "local_path": root_local_path,
                "remote_url": root_remote_url,
                "file_size": row["file_size"],
            }

        root_id = row["id"]
        source = row["source"]
        root_external_id = row["external_id"]
        root_name = row["name"]
        type_value = row["type_value"]

        composite_type = _asset_type_to_composite_type(str(type_value))

        # Create/Upsert the composite root (uses the *original* external_id)
        composite_meta = dict(meta)
        composite_meta.pop("variants", None)

        conn.execute(
            """
            INSERT INTO composites (
                id, source, external_id, name, composite_type,
                thumbnail_url, thumbnail_path, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, external_id) DO UPDATE SET
                id = excluded.id,
                name = excluded.name,
                composite_type = excluded.composite_type,
                thumbnail_url = excluded.thumbnail_url,
                thumbnail_path = excluded.thumbnail_path,
                metadata = excluded.metadata
            """,
            (
                root_id,
                source,
                root_external_id,
                root_name,
                composite_type.value,
                row["thumbnail_url"],
                row["thumbnail_path"],
                _encode_metadata_payload(composite_meta),
            ),
        )

        # re-write the root asset row as the base variant, and create additional leaf assets
        base = by_key[base_key]
        base_external_id = (
            root_external_id
            if root_external_id.endswith(f":{base_key}")
            else f"{root_external_id}:{base_key}"
        )

        base_meta = dict(composite_meta)
        # always override per-variant fields
        base_meta["resolution"] = base_key
        base_meta["role"] = base_key

        conn.execute(
            f"""
            UPDATE assets SET
                external_id = ?,
                name = ?,
                {type_col} = ?,
                status = ?,
                local_path = ?,
                remote_url = ?,
                thumbnail_url = ?,
                thumbnail_path = ?,
                file_size = ?,
                metadata = ?
            WHERE id = ?
            """,
            (
                base_external_id,
                f"{root_name} ({base_key})",
                str(type_value),
                str(base.get("status") or row["status"]),
                base.get("local_path") or root_local_path,
                base.get("remote_url") or root_remote_url,
                row["thumbnail_url"],
                row["thumbnail_path"],
                base.get("file_size") or row["file_size"],
                _encode_metadata_payload(base_meta),
                root_id,
            ),
        )

        for key in sorted(by_key.keys(), key=_resolution_sort_key):
            if key == base_key:
                continue

            v = by_key[key]
            child_id = f"{root_id}:{key}"
            child_external_id = f"{root_external_id}:{key}"
            child_meta = dict(composite_meta)
            # Always override per-variant fields.
            child_meta["resolution"] = key
            child_meta["role"] = key

            status_value = v.get("status")
            if not isinstance(status_value, str):
                status_value = (
                    AssetStatus.LOCAL.value
                    if v.get("local_path")
                    else AssetStatus.CLOUD.value
                )

            conn.execute(
                """
                INSERT INTO assets (
                    id, source, external_id, name, asset_type, status,
                    local_path, remote_url, thumbnail_url, thumbnail_path,
                    file_size, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, external_id) DO UPDATE SET
                    id = excluded.id,
                    name = excluded.name,
                    asset_type = excluded.asset_type,
                    status = excluded.status,
                    local_path = excluded.local_path,
                    remote_url = excluded.remote_url,
                    thumbnail_url = excluded.thumbnail_url,
                    thumbnail_path = excluded.thumbnail_path,
                    file_size = excluded.file_size,
                    metadata = excluded.metadata
                """,
                (
                    child_id,
                    source,
                    child_external_id,
                    f"{root_name} ({key})",
                    str(type_value),
                    status_value,
                    v.get("local_path"),
                    v.get("remote_url") or v.get("url"),
                    row["thumbnail_url"],
                    row["thumbnail_path"],
                    v.get("file_size") or v.get("size"),
                    _encode_metadata_payload(child_meta),
                ),
            )

        conn.execute(
            "DELETE FROM composite_children WHERE parent_composite_id = ?",
            (root_id,),
        )

        ordered_keys = sorted(by_key.keys(), key=_resolution_sort_key)
        for idx, key in enumerate(ordered_keys):
            child_id = root_id if key == base_key else f"{root_id}:{key}"
            conn.execute(
                """
                INSERT INTO composite_children (
                    parent_composite_id, child_asset_id, role, sort_order
                ) VALUES (?, ?, ?, ?)
                """,
                (root_id, child_id, key, idx),
            )


def _migrate_legacy_composite_members(conn: sqlite3.Connection, current_version: int) -> None:
    """Convert legacy composite_members table into composite_children if present."""
    if not _table_exists(conn, "composite_members"):
        return

    # Backup the legacy table for safety.
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS composite_members_backup_v{current_version} "
        "AS SELECT * FROM composite_members"
    )

    cols = _get_table_columns(conn, "composite_members")

    parent_col = "composite_id" if "composite_id" in cols else (
        "parent_id" if "parent_id" in cols else None
    )
    child_asset_col = "asset_id" if "asset_id" in cols else (
        "member_id" if "member_id" in cols else None
    )
    role_col = "role" if "role" in cols else None
    sort_col = "sort_order" if "sort_order" in cols else (
        "order" if "order" in cols else None
    )

    if not parent_col or not child_asset_col:
        # Can't interpret this table safely.
        return

    rows = list(
        conn.execute(
            f"SELECT * FROM composite_members ORDER BY {sort_col or parent_col}"
        )
    )

    # Group by parent, then replace children lists deterministically.
    by_parent: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        parent = r[parent_col]
        if not isinstance(parent, str) or not parent:
            continue
        by_parent.setdefault(parent, []).append(r)

    for parent, members in by_parent.items():
        conn.execute(
            "DELETE FROM composite_children WHERE parent_composite_id = ?",
            (parent,),
        )
        for idx, r in enumerate(members):
            child_id = r[child_asset_col]
            if not isinstance(child_id, str) or not child_id:
                continue
            role = r[role_col] if role_col else None
            sort_order = r[sort_col] if sort_col else idx
            try:
                sort_order_int = int(sort_order)
            except Exception:
                sort_order_int = idx

            conn.execute(
                """
                INSERT INTO composite_children (
                    parent_composite_id, child_asset_id, role, sort_order
                ) VALUES (?, ?, ?, ?)
                """,
                (parent, child_id, role, sort_order_int),
            )

    # Drop legacy table after successful conversion to avoid re-processing.
    conn.execute("DROP TABLE composite_members")


def migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Migrate legacy schema to v3 (recursive composition)."""
    current_version = _get_schema_version(conn) or 1
    if current_version >= SCHEMA_VERSION:
        return

    # NOTE: sqlite3.Connection.executescript() implicitly commits, so this avoids 
    # wrapping this migration in an explicit transaction, but still serialize
    # writes via the file lock at the AssetDatabase level

    # backup existing assets table 
    if _table_exists(conn, "assets"):
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS assets_backup_v{current_version} "
            "AS SELECT * FROM assets"
        )

    # Alter assets table to match new composite system columns
    assets_cols = _get_table_columns(conn, "assets")

    if "type" in assets_cols and "asset_type" not in assets_cols:
        conn.execute("ALTER TABLE assets RENAME COLUMN type TO asset_type")
        assets_cols.remove("type")
        assets_cols.add("asset_type")

    if "remote_url" not in assets_cols:
        conn.execute("ALTER TABLE assets ADD COLUMN remote_url TEXT")
        assets_cols.add("remote_url")

    if "file_size" not in assets_cols:
        conn.execute("ALTER TABLE assets ADD COLUMN file_size INTEGER")
        assets_cols.add("file_size")

    # Alter composites table if it exists (older schemas used `type`).
    if _table_exists(conn, "composites"):
        comp_cols = _get_table_columns(conn, "composites")
        if "type" in comp_cols and "composite_type" not in comp_cols:
            conn.execute(
                "ALTER TABLE composites RENAME COLUMN type TO composite_type")
            comp_cols.remove("type")
            comp_cols.add("composite_type")

        if "thumbnail_url" not in comp_cols:
            conn.execute("ALTER TABLE composites ADD COLUMN thumbnail_url TEXT")
            comp_cols.add("thumbnail_url")
        if "thumbnail_path" not in comp_cols:
            conn.execute("ALTER TABLE composites ADD COLUMN thumbnail_path TEXT")
            comp_cols.add("thumbnail_path")
        if "metadata" not in comp_cols:
            conn.execute("ALTER TABLE composites ADD COLUMN metadata TEXT")
            comp_cols.add("metadata")

    conn.execute("DROP VIEW IF EXISTS composite_tree")
    conn.executescript(_SCHEMA)

    conn.execute("BEGIN")
    try:
        _migrate_assets_with_variants(conn)
        _migrate_legacy_composite_members(conn, current_version=current_version)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    _set_schema_version(conn, SCHEMA_VERSION)


class AssetDatabase:
    """
    SQLite database for assets.
    """

    def __init__(self, db_path: Path | None = None):
        """
        Initialize the database.

        Args:
            db_path: Path to database file. Uses config.get_database_path() if not provided.
        """
        self.db_path = db_path or config.get_database_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.db_path.with_suffix(".lock")
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._write_lock(), self._connect() as conn:
            # Preflight legacy composite schemas: older DBs may have `composites.type`
            # instead of `composites.composite_type`, which breaks v3 index creatio
            if _table_exists(conn, "composites"):
                cols = _get_table_columns(conn, "composites")
                if "composite_type" not in cols:
                    if "type" in cols:
                        conn.execute(
                            "ALTER TABLE composites RENAME COLUMN type TO composite_type"
                        )
                    else:
                        conn.execute(
                            "ALTER TABLE composites ADD COLUMN composite_type TEXT"
                        )

                # Ensure v3 columns exist so `_SCHEMA` can create indexes safely.
                cols = _get_table_columns(conn, "composites")
                if "thumbnail_url" not in cols:
                    conn.execute(
                        "ALTER TABLE composites ADD COLUMN thumbnail_url TEXT"
                    )
                if "thumbnail_path" not in cols:
                    conn.execute(
                        "ALTER TABLE composites ADD COLUMN thumbnail_path TEXT"
                    )
                if "metadata" not in cols:
                    conn.execute(
                        "ALTER TABLE composites ADD COLUMN metadata TEXT"
                    )

            conn.executescript(_SCHEMA)

            current_version = _get_schema_version(conn)
            if current_version is None:
                # infer version from the assets table for robustness
                cols = _get_table_columns(conn, "assets")
                if "type" in cols and "asset_type" not in cols:
                    inferred = 1
                else:
                    # If required v3 columns are missing, treat as pre-v3.
                    required = {"asset_type", "remote_url", "file_size"}
                    inferred = SCHEMA_VERSION if required <= cols else 2
                _set_schema_version(conn, inferred)
                current_version = inferred

            if current_version < SCHEMA_VERSION:
                migrate_v2_to_v3(conn)
                current_version = SCHEMA_VERSION

            # ensure final schema objects exist
            conn.executescript(_SCHEMA)
            if _get_schema_version(conn) != SCHEMA_VERSION:
                _set_schema_version(conn, SCHEMA_VERSION)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Create a database connection with WAL mode and busy timeout."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=5.0,
            isolation_level=None,  # autocommit for WAL
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        """Acquire exclusive file lock for write operations."""
        # TODO: Support Windows with msvcrt.locking()
        self._lock_path.touch(exist_ok=True)
        with open(self._lock_path, "r") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _row_get(row: sqlite3.Row, key: str, default: Any = None) -> Any:
        return row[key] if key in row.keys() else default

    def _decode_metadata(self, payload: str | None) -> dict[str, Any]:
        if not payload:
            return {}
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _row_to_asset(self, row: sqlite3.Row) -> Asset:
        """Convert a database row to an `Asset`."""
        metadata = self._decode_metadata(self._row_get(row, "metadata"))
        asset_type_value = self._row_get(row, "asset_type")
        if asset_type_value is None and "type" in row.keys():
            asset_type_value = row["type"]

        return Asset.from_dict(
            {
                "id": row["id"],
                "source": row["source"],
                "external_id": row["external_id"],
                "name": row["name"],
                "asset_type": asset_type_value,
                "status": row["status"],
                "local_path": row["local_path"],
                "remote_url": self._row_get(row, "remote_url"),
                "thumbnail_url": row["thumbnail_url"],
                "thumbnail_path": row["thumbnail_path"],
                "file_size": self._row_get(row, "file_size"),
                "metadata": metadata,
            }
        )

    def _row_to_composite(self, row: sqlite3.Row) -> CompositeAsset:
        """Convert a database row to a `CompositeAsset` (no children loaded)."""
        metadata = self._decode_metadata(self._row_get(row, "metadata"))
        thumbnail_path = row["thumbnail_path"]
        return CompositeAsset(
            id=row["id"],
            source=row["source"],
            external_id=row["external_id"],
            name=row["name"],
            composite_type=CompositeType(row["composite_type"]),
            thumbnail_url=row["thumbnail_url"],
            thumbnail_path=Path(thumbnail_path) if thumbnail_path else None,
            metadata=metadata,
            children=[],
        )

    # TODO: figure out a better name for this method, this is ridiculous
    def get_already_downloaded_ids_compared_to_external_source(self, source: str, external_ids: list[str]) -> set[str]:
        """
        Batch lookup for comparing local database with external source.

        Returns the set of external_ids that are already downloaded in the database
        for the given source.

        Args:
            source: Plugin ID (e.g., "polyhaven")
            external_ids: List of external IDs to check

        Returns:
            Set of external_ids that exist locally
        """
        if not external_ids:
            return set()

        placeholders = ",".join("?" * len(external_ids))
        query = f"""
            SELECT external_id FROM assets
            WHERE source = ? AND external_id IN ({placeholders})
        """

        with self._connect() as conn:
            cursor = conn.execute(query, [source, *external_ids])
            return {row["external_id"] for row in cursor}

    def _upsert_asset_in_conn(self, conn: sqlite3.Connection, asset: Asset) -> None:
        conn.execute(
            """
            INSERT INTO assets (
                id, source, external_id, name, asset_type, status,
                local_path, remote_url, thumbnail_url, thumbnail_path,
                file_size, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, external_id) DO UPDATE SET
                id = excluded.id,
                name = excluded.name,
                asset_type = excluded.asset_type,
                status = excluded.status,
                local_path = excluded.local_path,
                remote_url = excluded.remote_url,
                thumbnail_url = excluded.thumbnail_url,
                thumbnail_path = excluded.thumbnail_path,
                file_size = excluded.file_size,
                metadata = excluded.metadata
            """,
            (
                asset.id,
                asset.source,
                asset.external_id,
                asset.name,
                asset.asset_type.value,
                asset.status.value,
                str(asset.local_path) if asset.local_path else None,
                asset.remote_url,
                asset.thumbnail_url,
                str(asset.thumbnail_path) if asset.thumbnail_path else None,
                asset.file_size,
                json.dumps(asset.metadata) if asset.metadata else None,
            ),
        )

    def upsert_asset(self, asset: Asset | StandardAsset) -> str:
        """Insert or update an asset."""
        asset_obj = asset.to_asset() if isinstance(asset, StandardAsset) else asset
        with self._write_lock(), self._connect() as conn:
            self._upsert_asset_in_conn(conn, asset_obj)
        return asset_obj.id

    def get_asset(self, asset_id: str) -> Asset | None:
        """Get a single asset by its internal ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
            return self._row_to_asset(row) if row else None

    def get_asset_by_external_id(self, source: str, external_id: str) -> Asset | None:
        """
        Get a single asset by source and external_id.

        Args:
            source: Plugin ID (e.g., "polyhaven")
            external_id: External ID from source

        Returns:
            The asset if found, None otherwise
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM assets WHERE source = ? AND external_id = ?",
                (source, external_id),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_asset(row)
            return None

    # Backwards-compatible alias
    def get_asset_by_id(self, asset_id: str) -> Asset | None:
        return self.get_asset(asset_id)

    def get_local_assets(self, source: str | None = None) -> list[Asset]:
        """
        Query assets with LOCAL status.

        Args:
            source: Optional plugin ID to filter by

        Returns:
            List of local assets
        """
        with self._connect() as conn:
            if source:
                cursor = conn.execute(
                    "SELECT * FROM assets WHERE status = ? AND source = ?",
                    (AssetStatus.LOCAL.value, source),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM assets WHERE status = ?",
                    (AssetStatus.LOCAL.value,),
                )
            return [self._row_to_asset(row) for row in cursor]

    def get_assets_by_source(self, source: str) -> list[Asset]:
        """
        Get all assets from a specific source.

        Args:
            source: Plugin ID

        Returns:
            List of assets from that source
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM assets WHERE source = ?",
                (source,),
            )
            return [self._row_to_asset(row) for row in cursor]

    def delete_asset(self, asset_id: str) -> bool:
        """Delete an asset by internal ID."""
        with self._write_lock(), self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM assets WHERE id = ?", (asset_id,))
            return cursor.rowcount > 0

    def remove_asset_by_external_id(self, source: str, external_id: str) -> bool:
        """
        Remove an asset record.

        Args:
            source: Plugin ID
            external_id: External ID from source

        Returns:
            True if an asset was deleted, False if not found
        """
        with self._write_lock(), self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM assets WHERE source = ? AND external_id = ?",
                (source, external_id),
            )
            return cursor.rowcount > 0

    def remove_asset_by_id(self, asset_id: str) -> bool:
        return self.delete_asset(asset_id)

    def search_assets(
        self,
        query: str,
        source: str | None = None,
        status: AssetStatus | None = None,
        asset_type: AssetType | None = None,
    ) -> list[Asset]:
        """
        Search assets by name.

        Args:
            query: Search string (matches against name)
            source: Optional plugin ID to filter by
            status: Optional status to filter by

        Returns:
            List of matching assets
        """
        conditions = ["name LIKE ?"]
        params: list[str] = [f"%{query}%"]

        if source:
            conditions.append("source = ?")
            params.append(source)

        if status:
            conditions.append("status = ?")
            params.append(status.value)

        if asset_type:
            conditions.append("asset_type = ?")
            params.append(asset_type.value)

        where_clause = " AND ".join(conditions)

        with self._connect() as conn:
            cursor = conn.execute(
                f"SELECT * FROM assets WHERE {where_clause}",
                params,
            )
            return [self._row_to_asset(row) for row in cursor]

    # Composites without children

    def _upsert_composite_in_conn(self, conn: sqlite3.Connection, composite: CompositeAsset) -> None:
        conn.execute(
            """
            INSERT INTO composites (
                id, source, external_id, name, composite_type,
                thumbnail_url, thumbnail_path, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, external_id) DO UPDATE SET
                id = excluded.id,
                name = excluded.name,
                composite_type = excluded.composite_type,
                thumbnail_url = excluded.thumbnail_url,
                thumbnail_path = excluded.thumbnail_path,
                metadata = excluded.metadata
            """,
            (
                composite.id,
                composite.source,
                composite.external_id,
                composite.name,
                composite.composite_type.value,
                composite.thumbnail_url,
                str(composite.thumbnail_path) if composite.thumbnail_path else None,
                json.dumps(composite.metadata) if composite.metadata else None,
            ),
        )

    def upsert_composite(self, composite: CompositeAsset) -> str:
        """Insert or update a composite (children are managed separately)."""
        with self._write_lock(), self._connect() as conn:
            self._upsert_composite_in_conn(conn, composite)
        return composite.id

    def get_composite(self, composite_id: str) -> CompositeAsset | None:
        """Get a composite by internal ID (no children loaded)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM composites WHERE id = ?",
                (composite_id,),
            ).fetchone()
            return self._row_to_composite(row) if row else None

    def get_composites_by_source(self, source: str) -> list[CompositeAsset]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM composites WHERE source = ?",
                (source,),
            )
            return [self._row_to_composite(row) for row in cursor]

    def delete_composite(self, composite_id: str) -> bool:
        """Delete a composite by internal ID (cascades child rows)."""
        with self._write_lock(), self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM composites WHERE id = ?",
                (composite_id,),
            )
            return cursor.rowcount > 0

    # Children management

    def set_composite_children(self, composite_id: str, children: list[Composable]) -> None:
        """Replace all children for a composite (ordered by input list)."""
        with self._write_lock(), self._connect() as conn:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    "DELETE FROM composite_children WHERE parent_composite_id = ?",
                    (composite_id,),
                )

                for idx, child in enumerate(children):
                    role = None
                    if isinstance(getattr(child, "metadata", None), dict):
                        role = child.metadata.get("role")

                    if isinstance(child, Asset):
                        self._upsert_asset_in_conn(conn, child)
                        conn.execute(
                            """
                            INSERT INTO composite_children (
                                parent_composite_id, child_asset_id, role, sort_order
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (composite_id, child.id, role, idx),
                        )
                    elif isinstance(child, CompositeAsset):
                        self._upsert_composite_in_conn(conn, child)
                        conn.execute(
                            """
                            INSERT INTO composite_children (
                                parent_composite_id, child_composite_id, role, sort_order
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (composite_id, child.id, role, idx),
                        )
                    else:
                        raise TypeError(
                            f"Unsupported child type: {type(child)}")

                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def get_composite_children(self, composite_id: str) -> list[Composable]:
        """Get direct children for a composite (ordered by sort_order)."""
        query = """
            SELECT
                cc.role,
                cc.sort_order,

                a.id AS a_id,
                a.source AS a_source,
                a.external_id AS a_external_id,
                a.name AS a_name,
                a.asset_type AS a_asset_type,
                a.status AS a_status,
                a.local_path AS a_local_path,
                a.remote_url AS a_remote_url,
                a.thumbnail_url AS a_thumbnail_url,
                a.thumbnail_path AS a_thumbnail_path,
                a.file_size AS a_file_size,
                a.metadata AS a_metadata,

                c.id AS c_id,
                c.source AS c_source,
                c.external_id AS c_external_id,
                c.name AS c_name,
                c.composite_type AS c_composite_type,
                c.thumbnail_url AS c_thumbnail_url,
                c.thumbnail_path AS c_thumbnail_path,
                c.metadata AS c_metadata

            FROM composite_children cc
            LEFT JOIN assets a ON cc.child_asset_id = a.id
            LEFT JOIN composites c ON cc.child_composite_id = c.id
            WHERE cc.parent_composite_id = ?
            ORDER BY cc.sort_order
        """

        with self._connect() as conn:
            cursor = conn.execute(query, (composite_id,))
            children: list[Composable] = []
            for row in cursor:
                role = row["role"]

                if row["a_id"] is not None:
                    metadata = self._decode_metadata(row["a_metadata"])
                    if role:
                        metadata = {**metadata, "role": role}
                    child = Asset.from_dict(
                        {
                            "id": row["a_id"],
                            "source": row["a_source"],
                            "external_id": row["a_external_id"],
                            "name": row["a_name"],
                            "asset_type": row["a_asset_type"],
                            "status": row["a_status"],
                            "local_path": row["a_local_path"],
                            "remote_url": row["a_remote_url"],
                            "thumbnail_url": row["a_thumbnail_url"],
                            "thumbnail_path": row["a_thumbnail_path"],
                            "file_size": row["a_file_size"],
                            "metadata": metadata,
                        }
                    )
                    children.append(child)
                    continue

                if row["c_id"] is not None:
                    metadata = self._decode_metadata(row["c_metadata"])
                    if role:
                        metadata = {**metadata, "role": role}
                    thumb_path = row["c_thumbnail_path"]
                    child = CompositeAsset(
                        id=row["c_id"],
                        source=row["c_source"],
                        external_id=row["c_external_id"],
                        name=row["c_name"],
                        composite_type=CompositeType(row["c_composite_type"]),
                        thumbnail_url=row["c_thumbnail_url"],
                        thumbnail_path=Path(
                            thumb_path) if thumb_path else None,
                        metadata=metadata,
                        children=[],
                    )
                    children.append(child)
                    continue

            return children

    def add_child_to_composite(self, parent_id: str, child: Composable, role: str) -> None:
        """Append a child to a composite."""
        with self._write_lock(), self._connect() as conn:
            conn.execute("BEGIN")
            try:
                row = conn.execute(
                    """
                    SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort
                    FROM composite_children
                    WHERE parent_composite_id = ?
                    """,
                    (parent_id,),
                ).fetchone()
                next_sort = int(
                    row["next_sort"]) if row and row["next_sort"] is not None else 0

                if isinstance(child, Asset):
                    self._upsert_asset_in_conn(conn, child)
                    conn.execute(
                        """
                        INSERT INTO composite_children (
                            parent_composite_id, child_asset_id, role, sort_order
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (parent_id, child.id, role, next_sort),
                    )
                elif isinstance(child, CompositeAsset):
                    self._upsert_composite_in_conn(conn, child)
                    conn.execute(
                        """
                        INSERT INTO composite_children (
                            parent_composite_id, child_composite_id, role, sort_order
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (parent_id, child.id, role, next_sort),
                    )
                else:
                    raise TypeError(f"Unsupported child type: {type(child)}")

                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def remove_child_from_composite(self, parent_id: str, child_id: str) -> bool:
        """Remove a child relationship from a composite."""
        with self._write_lock(), self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM composite_children
                WHERE parent_composite_id = ?
                  AND (child_asset_id = ? OR child_composite_id = ?)
                """,
                (parent_id, child_id, child_id),
            )
            return cursor.rowcount > 0

    # Recursive loading

    def get_composite_with_children(
        self,
        composite_id: str,
        depth: int = -1,
    ) -> CompositeAsset | None:
        """Load a composite with its children recursively."""

        def _load(
            conn: sqlite3.Connection,
            cid: str,
            remaining: int,
            stack: set[str],
        ) -> CompositeAsset | None:
            if cid in stack:
                # Circular reference safety: return stub without expanding further.
                return self.get_composite(cid)

            row = conn.execute(
                "SELECT * FROM composites WHERE id = ?",
                (cid,),
            ).fetchone()
            if not row:
                return None

            stack.add(cid)
            composite = self._row_to_composite(row)

            if remaining == 0:
                stack.remove(cid)
                return composite

            children = self.get_composite_children(cid)
            if remaining == 1:
                composite.children = children
                stack.remove(cid)
                return composite

            expanded: list[Composable] = []
            next_remaining = remaining if remaining < 0 else remaining - 1
            for child in children:
                if isinstance(child, Asset):
                    expanded.append(child)
                    continue

                if isinstance(child, CompositeAsset):
                    role = child.metadata.get("role") if isinstance(
                        child.metadata, dict) else None
                    loaded = _load(conn, child.id, next_remaining, stack)
                    if loaded is None:
                        expanded.append(child)
                        continue
                    if role:
                        loaded.metadata = {**loaded.metadata, "role": role}
                    expanded.append(loaded)
                    continue

            composite.children = expanded
            stack.remove(cid)
            return composite

        with self._connect() as conn:
            return _load(conn, composite_id, depth, set())
