"""Database queries for the runtimes table."""

from __future__ import annotations

from exwin.backend.runtime import Runtime
from exwin.db.schema import get_conn


def get_all_runtimes() -> list[Runtime]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM runtimes ORDER BY name COLLATE NOCASE").fetchall()
    return [Runtime.from_row(r) for r in rows]


def get_runtime(runtime_id: int) -> Runtime | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM runtimes WHERE id = ?", (runtime_id,)).fetchone()
    return Runtime.from_row(row) if row else None


def upsert_runtime(rt: Runtime) -> int:
    """Insert or update a runtime by path (unique key).  Returns the DB id."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO runtimes (name, type, path, version)
            VALUES (:name, :type, :path, :version)
            ON CONFLICT(path) DO UPDATE SET
                name    = excluded.name,
                version = excluded.version
            """,
            {"name": rt.name, "type": rt.type, "path": rt.path, "version": rt.version},
        )
        row = conn.execute("SELECT id FROM runtimes WHERE path = ?", (rt.path,)).fetchone()
    return row["id"]


def sync_runtimes(runtimes: list[Runtime]) -> list[Runtime]:
    """Upsert a list of scanned runtimes and return them with db_id populated."""
    result = []
    for rt in runtimes:
        db_id = upsert_runtime(rt)
        result.append(
            Runtime(
                name=rt.name,
                type=rt.type,
                path=rt.path,
                version=rt.version,
                db_id=db_id,
            )
        )
    return result
