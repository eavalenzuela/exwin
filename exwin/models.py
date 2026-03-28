"""In-memory data models for the application library."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class AppSource(StrEnum):
    GOG = "gog"
    MANUAL = "manual"


class RuntimeType(StrEnum):
    PROTON = "proton"
    WINE = "wine"


@dataclass
class AppEntry:
    app_id: str
    name: str
    source: AppSource
    install_path: Path | None = None
    prefix_path: Path | None = None
    exe_path: str = ""  # relative to install_path
    cover_art_path: Path | None = None
    description: str = ""
    install_date: str = ""
    last_launched: str = ""
    runtime_id: int | None = None
    playtime_seconds: int = 0
    tags: str = ""  # comma-separated tag list
    is_running: bool = field(default=False, compare=False)

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()] if self.tags else []

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> AppEntry:
        return cls(
            app_id=row["id"],
            name=row["name"],
            source=AppSource(row["source"]),
            install_path=Path(row["install_path"]) if row["install_path"] else None,
            prefix_path=Path(row["prefix_path"]) if row["prefix_path"] else None,
            exe_path=row["exe_path"] or "",
            cover_art_path=Path(row["cover_art_path"]) if row["cover_art_path"] else None,
            description=row["description"] or "",
            install_date=row["install_date"] or "",
            last_launched=row["last_launched"] or "",
            runtime_id=row["runtime_id"],
            playtime_seconds=row["playtime_seconds"] or 0,
            tags=row["tags"] or "",
        )
