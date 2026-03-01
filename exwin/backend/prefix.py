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
        # Proton will create and initialise pfx/ on first invocation.
        # Nothing to do here beyond ensuring the directory exists.
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


def delete_prefix(app_id: str, config: Config) -> None:
    """Recursively remove the Wine prefix for an app."""
    root = prefix_root(app_id, config)
    if root.exists():
        shutil.rmtree(root)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_env() -> dict[str, str]:
    return os.environ.copy()
