"""Database queries for the apps table."""

from __future__ import annotations

from exwin.db.schema import get_conn
from exwin.models import AppEntry


def get_all_apps() -> list[AppEntry]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM apps ORDER BY name COLLATE NOCASE").fetchall()
    return [AppEntry.from_row(r) for r in rows]


def get_app(app_id: str) -> AppEntry | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM apps WHERE id = ?", (app_id,)).fetchone()
    return AppEntry.from_row(row) if row else None


def delete_app(app_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM apps WHERE id = ?", (app_id,))


def insert_app(app: AppEntry) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO apps (id, name, source, install_path, prefix_path, exe_path,
                              runtime_id, cover_art_path, description, install_date)
            VALUES (:id, :name, :source, :install_path, :prefix_path, :exe_path,
                    :runtime_id, :cover_art_path, :description, :install_date)
            """,
            {
                "id": app.app_id,
                "name": app.name,
                "source": app.source,
                "install_path": app.install_path,
                "prefix_path": app.prefix_path,
                "exe_path": app.exe_path,
                "runtime_id": app.runtime_id,
                "cover_art_path": app.cover_art_path,
                "description": app.description,
                "install_date": app.install_date,
            },
        )


def update_last_launched(app_id: str, timestamp: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE apps SET last_launched = ? WHERE id = ?", (timestamp, app_id))


def update_description(app_id: str, description: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE apps SET description = ? WHERE id = ?", (description, app_id))


def update_cover_art(app_id: str, path: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE apps SET cover_art_path = ? WHERE id = ?", (path, app_id))


def update_playtime(app_id: str, elapsed_seconds: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE apps SET playtime_seconds = playtime_seconds + ? WHERE id = ?",
            (elapsed_seconds, app_id),
        )


def update_paths(app_id: str, install_path: str, prefix_path: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE apps SET install_path = ?, prefix_path = ? WHERE id = ?",
            (install_path, prefix_path, app_id),
        )


def update_runtime(app_id: str, runtime_id: int | None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE apps SET runtime_id = ? WHERE id = ?", (runtime_id, app_id))
