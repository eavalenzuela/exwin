"""Wine prefix creation and deletion."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from exwin.backend.config import Config
from exwin.backend.runtime import Runtime


def prefix_root(app_id: str, config: Config) -> Path:
    """Return the prefix root directory for an app (always exists after create_prefix)."""
    return config.prefixes_dir / app_id


def wineprefix_path(app_id: str, config: Config, runtime: Runtime) -> Path:
    """Return the actual WINEPREFIX path for an app given its runtime type.

    Proton: <prefix_root>/pfx  (Proton manages the pfx/ subdirectory)
    Wine:   <prefix_root>      (the root IS the WINEPREFIX)
    """
    root = prefix_root(app_id, config)
    return root / "pfx" if runtime.is_proton else root


def create_prefix(app_id: str, config: Config, runtime: Runtime, arch: str = "win64") -> Path:
    """Create and initialise a Wine prefix for an app.

    Returns the prefix root path (suitable for STEAM_COMPAT_DATA_PATH with
    Proton, or the WINEPREFIX directly with vanilla Wine).
    """
    root = prefix_root(app_id, config)
    root.mkdir(parents=True, exist_ok=True)

    if runtime.is_proton:
        # Proton writes a 'version' file at the compat data root once its
        # init has copied default_pfx and bootstrapped the registry.  If the
        # file is missing, either the prefix is fresh or it was partially
        # created by winetricks/wine64 (which skips Proton's init path).
        # A partial init leaves 32-bit COM registrations (e.g. the
        # Wow6432Node DirectSound class) absent, breaking many 32-bit games.
        if not (root / "version").exists():
            _init_proton_prefix(root, runtime)
        return root

    # Vanilla Wine: initialise the prefix with wineboot.
    env = _base_env()
    env["WINEPREFIX"] = str(root)
    env["WINEARCH"] = arch

    subprocess.run(
        [str(runtime.wine_binary), "wineboot", "--init"],
        env=env,
        check=False,  # wineboot may exit non-zero on first run; that's fine
        timeout=120,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return root


def rebuild_prefix(app_id: str, config: Config, runtime: Runtime, arch: str = "win64") -> Path:
    """Delete and recreate the Wine prefix for *app_id* from scratch.

    Any state inside the prefix (installed winetricks verbs, DLLs, registry
    entries) is lost.  Game files stored outside the prefix are unaffected.
    """
    delete_prefix(app_id, config)
    return create_prefix(app_id, config, runtime, arch)


def delete_prefix(app_id: str, config: Config) -> None:
    """Recursively remove the Wine prefix for an app."""
    root = prefix_root(app_id, config)
    if root.exists():
        shutil.rmtree(root)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_proton_prefix(prefix_root_dir: Path, runtime: Runtime) -> None:
    """Trigger Proton's prefix bootstrap.

    Any Proton invocation runs its setup logic first: copy default_pfx,
    bootstrap the full registry (including Wow6432Node), and write the
    'version' marker.  We chain a no-op wineboot --end-session so the
    wineserver spawned by init terminates cleanly before we return.
    """
    env = _base_env()
    env["STEAM_COMPAT_DATA_PATH"] = str(prefix_root_dir)
    env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = str(Path.home() / ".steam" / "root")
    # Non-Steam game markers — ProtonFixes' get_game_id() reads these and
    # otherwise tries to extract digits from STEAM_COMPAT_DATA_PATH (which
    # fails for our non-numeric prefix paths).
    env["SteamAppId"] = "0"
    env["SteamGameId"] = "0"

    subprocess.run(
        [str(runtime.proton_binary), "run", "wineboot", "--end-session"],
        env=env,
        check=False,
        timeout=300,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _base_env() -> dict[str, str]:
    return os.environ.copy()
