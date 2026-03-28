"""Automatic save file path detection for Wine/Proton prefixes."""

from __future__ import annotations

from pathlib import Path

from exwin.models import AppEntry


def detect_save_paths(app: AppEntry) -> list[Path]:
    """Scan common save file locations within the app's Wine prefix and install dir.

    Returns a list of existing directories that likely contain save files,
    sorted with the most specific paths first.
    """
    results: list[Path] = []

    prefix = app.prefix_path
    install = app.install_path

    if prefix:
        # Proton uses pfx/ subdirectory; plain Wine uses the root directly
        pfx_dir = prefix / "pfx" if (prefix / "pfx").is_dir() else prefix
        drive_c = pfx_dir / "drive_c"

        # Scan each user directory under drive_c
        users_dir = drive_c / "users"
        if users_dir.is_dir():
            for user_dir in users_dir.iterdir():
                if not user_dir.is_dir() or user_dir.name == "Public":
                    continue
                _check_user_dirs(user_dir, results)

    # Game's own install directory (some games save next to the exe)
    if install and install.is_dir():
        for name in ("saves", "save", "Saves", "Save", "savegames", "SaveGames"):
            candidate = install / name
            if candidate.is_dir():
                results.append(candidate)

    return results


def _check_user_dirs(user_dir: Path, results: list[Path]) -> None:
    """Check common save locations under a Wine user directory."""
    candidates = [
        user_dir / "AppData" / "Local",
        user_dir / "AppData" / "Roaming",
        user_dir / "AppData" / "LocalLow",
        user_dir / "Documents" / "My Games",
        user_dir / "Documents",
        user_dir / "Saved Games",
    ]
    for d in candidates:
        if d.is_dir() and any(d.iterdir()):
            results.append(d)
