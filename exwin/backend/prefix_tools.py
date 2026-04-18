"""Wine prefix tools — run winecfg, regedit, wineserver -k, wineboot -u."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from exwin.backend.runtime import Runtime

# Mirrors launcher._STEAM_ROOT — used for Proton compat-data env when
# invoking wineboot -u outside a full launch.
_STEAM_ROOT = Path.home() / ".steam" / "root"


def _prefix_env(prefix_path: Path, runtime: Runtime) -> dict[str, str]:
    """Build the environment dict for running Wine tools against a prefix."""
    env = os.environ.copy()

    if runtime.is_proton:
        env["WINEPREFIX"] = str(prefix_path / "pfx")
        env["WINE"] = str(runtime.wine_binary)
        env["WINESERVER"] = str(runtime.path / "files" / "bin" / "wineserver")
    else:
        env["WINEPREFIX"] = str(prefix_path)

    return env


def run_winecfg(prefix_path: Path, runtime: Runtime) -> subprocess.Popen:
    """Launch winecfg for the given prefix."""
    env = _prefix_env(prefix_path, runtime)
    return subprocess.Popen(
        [str(runtime.wine_binary), "winecfg"],
        env=env,
        start_new_session=True,
    )


def run_regedit(prefix_path: Path, runtime: Runtime) -> subprocess.Popen:
    """Launch regedit for the given prefix."""
    env = _prefix_env(prefix_path, runtime)
    return subprocess.Popen(
        [str(runtime.wine_binary), "regedit"],
        env=env,
        start_new_session=True,
    )


def upgrade_prefix(prefix_path: Path, runtime: Runtime, **popen_kwargs) -> subprocess.Popen:
    """Run ``wineboot -u`` against *prefix_path* to refresh system DLLs.

    Unlike :func:`prefix.rebuild_prefix`, this keeps user data intact — it's
    the right call after switching runtimes (e.g. Proton 9 → Proton 10) so
    the bundled system DLLs line up with the new Wine version.

    Returns the :class:`subprocess.Popen`; caller waits or streams output.
    """
    if runtime.is_proton:
        # Proton path: invoke the Proton binary directly so its prefix-setup
        # bootstrap runs. env mirrors Launcher._build_env for Proton.
        env = os.environ.copy()
        env["STEAM_COMPAT_DATA_PATH"] = str(prefix_path)
        env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = str(_STEAM_ROOT) if _STEAM_ROOT.exists() else ""
        env.setdefault("SteamAppId", "0")
        env.setdefault("SteamGameId", "0")
        cmd = [str(runtime.proton_binary), "run", "wineboot", "-u"]
    else:
        env = _prefix_env(prefix_path, runtime)
        cmd = [str(runtime.wine_binary), "wineboot", "-u"]
    return subprocess.Popen(cmd, env=env, **popen_kwargs)


def kill_prefix(prefix_path: Path, runtime: Runtime) -> None:
    """Kill all processes in the Wine prefix via wineserver -k."""
    env = _prefix_env(prefix_path, runtime)
    if runtime.is_proton:
        wineserver = str(runtime.path / "files" / "bin" / "wineserver")
    else:
        wineserver = str(runtime.path / "bin" / "wineserver")
    subprocess.run(
        [wineserver, "-k"],
        env=env,
        check=False,
        timeout=15,
    )
