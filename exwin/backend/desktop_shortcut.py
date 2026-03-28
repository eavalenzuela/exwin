"""Generate a .desktop launcher file for an installed app."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from exwin.models import AppEntry

_APPLICATIONS_DIR = Path.home() / ".local" / "share" / "applications"


def create_shortcut(app: AppEntry) -> Path:
    """Write a .desktop file for *app* and return its path.

    The Exec= line delegates to ``sys.executable -m exwin --launch <app_id>``
    so that all per-app settings (GPU, env vars, DLL overrides, etc.) are
    always applied at launch time.
    """
    _APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _APPLICATIONS_DIR / f"exwin-{app.app_id}.desktop"

    icon = (
        str(app.cover_art_path)
        if (app.cover_art_path and app.cover_art_path.exists())
        else "applications-games-symbolic"
    )
    exec_cmd = f"{sys.executable} -m exwin --launch {app.app_id}"

    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={app.name}",
        f"Exec={exec_cmd}",
        f"Icon={icon}",
        "Categories=Game;",
        "StartupNotify=true",
    ]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Inform the desktop environment; ignore errors (may not be installed)
    if shutil.which("update-desktop-database"):
        subprocess.run(
            ["update-desktop-database", str(_APPLICATIONS_DIR)],
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return dest
