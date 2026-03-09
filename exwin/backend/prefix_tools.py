"""Wine prefix tools — run winecfg, regedit, wineserver -k."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from exwin.backend.runtime import Runtime


def _prefix_env(prefix_path: str, runtime: Runtime) -> dict[str, str]:
    """Build the environment dict for running Wine tools against a prefix."""
    env = os.environ.copy()
    prefix_root = Path(prefix_path)

    if runtime.is_proton:
        env["WINEPREFIX"] = str(prefix_root / "pfx")
        env["WINE"] = str(runtime.wine_binary)
        env["WINESERVER"] = str(Path(runtime.path) / "files" / "bin" / "wineserver")
    else:
        env["WINEPREFIX"] = str(prefix_root)

    return env


def run_winecfg(prefix_path: str, runtime: Runtime) -> subprocess.Popen:
    """Launch winecfg for the given prefix."""
    env = _prefix_env(prefix_path, runtime)
    return subprocess.Popen(
        [str(runtime.wine_binary), "winecfg"],
        env=env,
        start_new_session=True,
    )


def run_regedit(prefix_path: str, runtime: Runtime) -> subprocess.Popen:
    """Launch regedit for the given prefix."""
    env = _prefix_env(prefix_path, runtime)
    return subprocess.Popen(
        [str(runtime.wine_binary), "regedit"],
        env=env,
        start_new_session=True,
    )


def kill_prefix(prefix_path: str, runtime: Runtime) -> None:
    """Kill all processes in the Wine prefix via wineserver -k."""
    env = _prefix_env(prefix_path, runtime)
    if runtime.is_proton:
        wineserver = str(Path(runtime.path) / "files" / "bin" / "wineserver")
    else:
        wineserver = str(Path(runtime.path) / "bin" / "wineserver")
    subprocess.run(
        [wineserver, "-k"],
        env=env,
        check=False,
        timeout=15,
    )
