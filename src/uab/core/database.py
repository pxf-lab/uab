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
