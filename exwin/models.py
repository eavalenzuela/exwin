"""In-memory data models for the application library."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass
class AppEntry:
    app_id: str
    name: str
    source: str  # "gog" | "manual"
    install_path: str = ""
    prefix_path: str = ""
    exe_path: str = ""  # relative to install_path
    cover_art_path: str = ""
    description: str = ""
    install_date: str = ""
    last_launched: str = ""
    runtime_id: int | None = None
    is_running: bool = field(default=False, compare=False)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> AppEntry:
        return cls(
            app_id=row["id"],
            name=row["name"],
            source=row["source"],
            install_path=row["install_path"] or "",
            prefix_path=row["prefix_path"] or "",
            exe_path=row["exe_path"] or "",
            cover_art_path=row["cover_art_path"] or "",
            description=row["description"] or "",
            install_date=row["install_date"] or "",
            last_launched=row["last_launched"] or "",
            runtime_id=row["runtime_id"],
        )
