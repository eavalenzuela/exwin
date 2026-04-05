"""Winetricks integration — run verb lists against a Wine prefix."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import IO, Any

from exwin.backend.runtime import Runtime


def is_available() -> bool:
    return shutil.which("winetricks") is not None


def run_verbs(
    prefix_root: Path,
    verbs: list[str],
    runtime: Runtime | None = None,
    *,
    unattended: bool = True,
    stdout: IO[Any] | int | None = None,
    stderr: IO[Any] | int | None = None,
) -> subprocess.Popen:
    """Spawn winetricks to install *verbs* into *prefix_root*.

    Args:
        prefix_root: The prefix root directory (STEAM_COMPAT_DATA_PATH for
                     Proton, or directly the WINEPREFIX for vanilla Wine).
        verbs:       List of winetricks verbs (e.g. ["vcredist2019", "dxvk"]).
        runtime:     Optional runtime; if a Proton runtime is provided its
                     bundled wine/wineserver binaries are used.
        unattended:  Pass --unattended to suppress GUI installers.
        stdout:      File object or subprocess constant for the child's stdout.
                     Defaults to inheriting from the parent.
        stderr:      Same as stdout for stderr.  Pass ``subprocess.STDOUT`` to
                     merge stderr into stdout.

    Returns:
        The spawned Popen object.  Callers are responsible for waiting on it.
    """
    if not is_available():
        raise RuntimeError("winetricks not found in PATH")
    if not verbs:
        raise ValueError("No winetricks verbs specified")

    env = os.environ.copy()

    if runtime and runtime.is_proton:
        wineprefix = str(prefix_root / "pfx")
        env["WINEPREFIX"] = wineprefix
        # Point winetricks at Proton's bundled wine binaries.  We use wine64
        # (via runtime.wine_binary) for $WINE — Proton's 32-bit `wine` binary
        # requires /lib/ld-linux.so.2 which isn't present in sandboxes like
        # Flatpak.  Modern Wine (wow64) can install 32-bit DLLs via wine64.
        proton_bin = runtime.path / "files" / "bin"
        env["WINE"] = str(runtime.wine_binary)
        env["WINE64"] = str(proton_bin / "wine64")
        env["WINESERVER"] = str(proton_bin / "wineserver")
    else:
        env["WINEPREFIX"] = str(prefix_root)

    cmd = ["winetricks"]
    if unattended:
        cmd.append("--unattended")
    cmd.extend(verbs)

    return subprocess.Popen(cmd, env=env, stdout=stdout, stderr=stderr)
