"""SQLite schema initialisation and connection helper."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

_DB_PATH: Path | None = None

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runtimes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,          -- e.g. "GE-Proton9-27", "system-wine"
    type     TEXT NOT NULL           -- "proton" | "wine"
                 CHECK (type IN ('proton', 'wine')),
    path     TEXT NOT NULL UNIQUE,   -- absolute path to runtime directory
    version  TEXT                    -- free-form version string
);

CREATE TABLE IF NOT EXISTS apps (
    id            TEXT PRIMARY KEY,  -- url-safe slug, e.g. "witcher-3"
    name          TEXT NOT NULL,
    source        TEXT NOT NULL      -- "gog" | "manual" | ...
                      CHECK (source IN ('gog', 'manual')),
    install_path  TEXT,              -- absolute path to installed game files
    prefix_path   TEXT,              -- absolute path to WINEPREFIX
    exe_path      TEXT,              -- path to main exe, relative to install_path
    runtime_id    INTEGER REFERENCES runtimes (id) ON DELETE SET NULL,
    cover_art_path TEXT,
    description   TEXT,
    install_date  TEXT,              -- ISO 8601 datetime
    last_launched TEXT,              -- ISO 8601 datetime, NULL if never run
    playtime_seconds INTEGER DEFAULT 0
);
"""


def init_db(data_dir: Path) -> None:
    """Create the database and apply the schema. Safe to call on every startup."""
    global _DB_PATH
    _DB_PATH = data_dir / "library.db"
    with sqlite3.connect(_DB_PATH) as conn:
        conn.executescript(_SCHEMA)
        try:
            conn.execute("ALTER TABLE apps ADD COLUMN playtime_seconds INTEGER DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Context manager yielding a WAL-enabled, row_factory connection."""
    if _DB_PATH is None:
        raise RuntimeError("Database not initialised — call init_db() first.")
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
