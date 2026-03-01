"""Wine/Proton runtime detection and representation."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Canonical scan roots — ~/.steam/root is a distro-agnostic symlink to the
# actual Steam installation (debian-installation, steam, etc.)
_PROTON_SCAN_ROOTS: list[Path] = [
    Path.home() / ".steam" / "root" / "steamapps" / "common",
    Path.home() / ".steam" / "root" / "compatibilitytools.d",
    Path.home() / ".local" / "share" / "Steam" / "steamapps" / "common",
    Path.home() / ".local" / "share" / "Steam" / "compatibilitytools.d",
]


@dataclass
class Runtime:
    name: str
    type: str  # "proton" | "wine"
    path: str  # Proton: root dir of runtime; Wine: prefix of the installation (e.g. /usr)
    version: str = ""
    db_id: int | None = field(default=None, compare=False)

    @property
    def is_proton(self) -> bool:
        return self.type == "proton"

    @property
    def proton_binary(self) -> Path:
        return Path(self.path) / "proton"

    @property
    def wine_binary(self) -> Path:
        if self.is_proton:
            # Proton bundles wine at files/bin/wine
            return Path(self.path) / "files" / "bin" / "wine"
        return Path(self.path) / "bin" / "wine"

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Runtime:
        return cls(
            db_id=row["id"],
            name=row["name"],
            type=row["type"],
            path=row["path"],
            version=row["version"] or "",
        )

    def __str__(self) -> str:
        return self.name


def scan_runtimes() -> list[Runtime]:
    """Detect all available Proton and Wine runtimes on the system."""
    found: list[Runtime] = []
    seen_paths: set[str] = set()

    # ── Proton ──────────────────────────────────────────────────────────
    for root in _PROTON_SCAN_ROOTS:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            proton_bin = entry / "proton"
            if not proton_bin.is_file():
                continue
            path_str = str(entry.resolve())
            if path_str in seen_paths:
                continue
            seen_paths.add(path_str)
            found.append(
                Runtime(
                    name=entry.name,
                    type="proton",
                    path=path_str,
                    version=_read_proton_version(entry),
                )
            )

    # ── System Wine ─────────────────────────────────────────────────────
    wine_exe = shutil.which("wine")
    if wine_exe:
        # Derive install prefix: /usr/bin/wine → /usr
        prefix = str(Path(wine_exe).resolve().parent.parent)
        if prefix not in seen_paths:
            seen_paths.add(prefix)
            found.append(
                Runtime(
                    name=f"Wine ({_read_wine_version(wine_exe)})",
                    type="wine",
                    path=prefix,
                    version=_read_wine_version(wine_exe),
                )
            )

    return found


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_proton_version(proton_dir: Path) -> str:
    """Read the version string from Proton's 'version' file."""
    version_file = proton_dir / "version"
    if version_file.exists():
        text = version_file.read_text().strip()
        # Format: "<timestamp> <version-string>"  e.g. "1769167055 proton-10.0-4"
        parts = text.split(None, 1)
        if len(parts) == 2:
            return parts[1]
        return text
    return proton_dir.name  # fall back to directory name


def _read_wine_version(wine_exe: str) -> str:
    """Run 'wine --version' to get the version string."""
    try:
        result = subprocess.run(
            [wine_exe, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"
