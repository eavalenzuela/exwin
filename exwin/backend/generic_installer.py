"""Detection and Wine-based installation for non-GOG/non-InnoSetup .exe installers."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from exwin.backend.app_config import AppConfig, save_app_config
from exwin.backend.config import Config
from exwin.backend.gog_installer import find_innoextract
from exwin.backend.runtime import Runtime
from exwin.backend.winetricks import is_available as winetricks_available
from exwin.backend.winetricks import run_verbs
from exwin.db.apps import insert_app
from exwin.models import AppEntry

_SKIP_DIRS = {"__redist", "unins", "uninstall", "setup", "vcredist", "dotnet", "isisetup"}
_SKIP_EXES = {"unins000.exe", "uninst.exe", "uninstall.exe", "setup.exe"}


def detect_installer_type(installer_path: Path) -> str:
    """Return ``"innosetup"`` if the file is an InnoSetup installer, else ``"generic"``.

    Uses ``innoextract --data-version`` which exits 0 for InnoSetup and non-zero
    (or raises) for everything else.
    """
    try:
        binary = find_innoextract()
    except RuntimeError:
        return "generic"

    result = subprocess.run(
        [binary, "--data-version", str(installer_path)],
        capture_output=True,
        timeout=15,
    )
    return "innosetup" if result.returncode == 0 else "generic"


def run_wine_installer(
    installer_path: Path,
    p_root: Path,
    runtime: Runtime | None,
    arch: str = "win64",
) -> subprocess.Popen:
    """Create a Wine prefix and launch *installer_path* interactively.

    The Windows installer GUI will appear on-screen; the caller is responsible
    for watching the returned Popen and reacting when it exits.

    Args:
        installer_path: The .exe installer to run.
        p_root:         The prefix root directory (STEAM_COMPAT_DATA_PATH or WINEPREFIX).
        runtime:        The Wine/Proton runtime to use, or None for system Wine.
        arch:           ``"win32"`` or ``"win64"`` for the Wine prefix.

    Returns:
        A running :class:`subprocess.Popen` object.
    """
    p_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()

    if runtime and runtime.is_proton:
        cmd = [str(runtime.proton_binary), "run", str(installer_path)]
        env["STEAM_COMPAT_DATA_PATH"] = str(p_root)
        env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = str(Path.home() / ".steam" / "root")
    else:
        wine_bin = str(runtime.wine_binary) if runtime else "wine"
        cmd = [wine_bin, str(installer_path)]
        env["WINEPREFIX"] = str(p_root)
        env["WINEARCH"] = arch

    return subprocess.Popen(cmd, env=env)


def scan_candidate_exes(p_root: Path, runtime: Runtime | None) -> list[Path]:
    """Return .exe files found in the Wine prefix drive_c directory.

    Results are sorted with shallow paths first (more likely to be the main exe).
    Paths are absolute.
    """
    if runtime and runtime.is_proton:
        drive_c = p_root / "pfx" / "drive_c"
    else:
        drive_c = p_root / "drive_c"

    if not drive_c.is_dir():
        return []

    candidates = []
    for exe in drive_c.rglob("*.exe"):
        lower = exe.name.lower()
        if lower in _SKIP_EXES:
            continue
        if any(skip in str(exe).lower() for skip in _SKIP_DIRS):
            continue
        candidates.append(exe)

    return sorted(candidates, key=lambda p: (len(p.parts), p.name.lower()))


def finalize_generic_install(
    app_name: str,
    p_root: Path,
    exe_abs: Path,
    config: Config,
    runtime: Runtime | None,
    arch: str = "win64",
    winetricks_verbs: list[str] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> AppEntry:
    """Persist a generic Wine-installed app to the library.

    Args:
        app_name:  Display name for the app (usually the installer filename stem).
        p_root:    The prefix root directory used during installation.
        exe_abs:   Absolute path to the selected main executable.
        config:    Global exwin Config.
        runtime:   The runtime used.
        arch:      Wine architecture.
        winetricks_verbs: Optional list of verbs to run post-install.

    Returns:
        The newly created :class:`AppEntry`.
    """

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    app_id = _slugify_app_id(app_name)

    # Apply winetricks if requested
    verbs = winetricks_verbs or []
    if verbs:
        if not winetricks_available():
            _log("Warning: winetricks not found — skipping verb installation.")
        else:
            _log(f"Applying winetricks: {' '.join(verbs)}")
            proc = run_verbs(p_root, verbs, runtime)
            proc.wait()
            rc = proc.returncode
            _log(
                f"winetricks finished (exit code {rc})"
                f"{'.' if rc == 0 else ' — check logs for errors.'}"
            )

    # Save per-app config
    app_config = AppConfig(arch=arch, winetricks_verbs=verbs)
    save_app_config(app_id, config, app_config)

    # exe_path stored relative to prefix root so the launcher can resolve it
    try:
        exe_rel = str(exe_abs.relative_to(p_root))
    except ValueError:
        exe_rel = str(exe_abs)

    app = AppEntry(
        app_id=app_id,
        name=app_name,
        source="manual",
        install_path=str(p_root),
        prefix_path=str(p_root),
        exe_path=exe_rel,
        cover_art_path="",
        install_date=datetime.now(UTC).isoformat(),
        runtime_id=runtime.db_id if runtime else None,
    )
    insert_app(app)
    _log(f'✓ "{app_name}" added to library.')
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify_app_id(name: str) -> str:
    slug = re.sub(r"\W+", "-", name.lower()).strip("-")
    return f"manual-{slug}"
