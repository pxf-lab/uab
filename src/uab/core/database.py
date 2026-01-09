"""SQLite database for asset persistence with file locking."""

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from uab.core.models import AssetStatus, StandardAsset

# Default database location
# TODO: Support Windows with %APPDATA% (I think?)
# TODO: Support Linux
DATABASE_PATH_DEFAULT = Path.home() / "library" / "application support" / \
    "com.pixelfoundry" / "uab" / "assets.db"

# Schema version for future migrations
SCHEMA_VERSION = 1

_SCHEMA = """
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

CREATE INDEX IF NOT EXISTS idx_source ON assets(source);
CREATE INDEX IF NOT EXISTS idx_status ON assets(status);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""


class AssetDatabase:
    """
    SQLite database for assets.
    """

    def __init__(self, db_path: Path | None = None):
        """
        Initialize the database.

        Args:
            db_path: Path to database file. Defaults to ~/.uab/assets.db
        """
        self.db_path = db_path or DATABASE_PATH_DEFAULT
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.db_path.with_suffix(".lock")
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
            if cursor.fetchone() is None:
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )

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

    def _row_to_asset(self, row: sqlite3.Row) -> StandardAsset:
        """Convert a database row to a StandardAsset."""
        metadata = row["metadata"]
        if metadata:
            metadata = json.loads(metadata)
        else:
            metadata = {}

        return StandardAsset.from_dict({
            "id": row["id"],
            "source": row["source"],
            "external_id": row["external_id"],
            "name": row["name"],
            "type": row["type"],
            "status": row["status"],
            "local_path": row["local_path"],
            "thumbnail_url": row["thumbnail_url"],
            "thumbnail_path": row["thumbnail_path"],
            "metadata": metadata,
        })
