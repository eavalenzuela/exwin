"""Scan an install directory for bundled redistributable installers.

Many games ship vendor prereqs (VC++ runtimes, DirectX, OpenAL, UE prereq
bundles, PhysX) inside a ``__redist``/``_CommonRedist`` folder.  Wine/Proton
doesn't auto-run those the way Steam does on Windows — so games crash at
launch with "missing MSVCP140.dll".

This module walks the install dir, matches filenames against a curated
pattern list, and returns a list of :class:`RedistFinding`.  The caller
picks which to apply; each finding is either ``"run"`` (execute the bundled
installer under Wine) or ``"verb"`` (install the equivalent winetricks verb,
which is usually faster and more reliable than the vendor installer).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from exwin.backend.runtime import Runtime
from exwin.backend.winetricks import run_verbs


@dataclass(frozen=True)
class RedistFinding:
    path: Path
    kind: str
    description: str
    action: str  # "run" | "verb"
    payload: str
    recommended: bool = True


# ---------------------------------------------------------------------------
# Pattern catalogue
# ---------------------------------------------------------------------------
# Tuple layout: (filename regex (case-insensitive), kind, description, action,
# payload, recommended).  Order matters — more specific patterns first, since
# the first match wins per file.

_PATTERNS: list[tuple[str, str, str, str, str, bool]] = [
    # --- Visual C++ redistributables → prefer winetricks verbs -------------
    (
        r"vc_?redist.*(x64|amd64).*\.exe$",
        "vcredist-2015-2019-x64",
        "Visual C++ 2015-2019 Redistributable (x64)",
        "verb",
        "vcrun2019",
        True,
    ),
    (
        r"vc_?redist.*x86.*\.exe$",
        "vcredist-2015-2019-x86",
        "Visual C++ 2015-2019 Redistributable (x86)",
        "verb",
        "vcrun2019",
        True,
    ),
    (
        r"vcredist_?2013.*\.exe$",
        "vcredist-2013",
        "Visual C++ 2013 Redistributable",
        "verb",
        "vcrun2013",
        True,
    ),
    (
        r"vcredist_?2012.*\.exe$",
        "vcredist-2012",
        "Visual C++ 2012 Redistributable",
        "verb",
        "vcrun2012",
        True,
    ),
    (
        r"vcredist_?2010.*\.exe$",
        "vcredist-2010",
        "Visual C++ 2010 Redistributable",
        "verb",
        "vcrun2010",
        True,
    ),
    (
        r"vcredist_?2008.*\.exe$",
        "vcredist-2008",
        "Visual C++ 2008 Redistributable",
        "verb",
        "vcrun2008",
        True,
    ),
    (
        r"vcredist_?2005.*\.exe$",
        "vcredist-2005",
        "Visual C++ 2005 Redistributable",
        "verb",
        "vcrun2005",
        True,
    ),
    # --- DirectX (DXSetup bundle) — still best run under Wine --------------
    (
        r"dxsetup\.exe$",
        "dxsetup",
        "DirectX End-User Runtime",
        "run",
        "/silent",
        True,
    ),
    # --- .NET Framework ----------------------------------------------------
    (
        r"ndp48.*\.exe$",
        "dotnet48",
        ".NET Framework 4.8",
        "verb",
        "dotnet48",
        True,
    ),
    (
        r"dotnetfx(35|40|45)?\.exe$",
        "dotnetfx",
        ".NET Framework (generic)",
        "verb",
        "dotnet48",
        False,
    ),
    # --- Unreal Engine prereqs --------------------------------------------
    (
        r"ue[34]prereqsetup_x64\.exe$",
        "ue-prereq-x64",
        "Unreal Engine Prerequisites (x64)",
        "run",
        "/quiet /norestart",
        True,
    ),
    (
        r"ue[34]prereqsetup_x86\.exe$",
        "ue-prereq-x86",
        "Unreal Engine Prerequisites (x86)",
        "run",
        "/quiet /norestart",
        True,
    ),
    # --- OpenAL (many older engines) --------------------------------------
    (
        r"oalinst\.exe$",
        "openal",
        "OpenAL runtime",
        "run",
        "/s",
        True,
    ),
    # --- PhysX ------------------------------------------------------------
    (
        r"physx.*systemsoftware.*\.exe$",
        "physx",
        "NVIDIA PhysX runtime",
        "run",
        "/passive /norestart",
        False,
    ),
    # --- XNA --------------------------------------------------------------
    (
        r"xnafx40_redist\.msi$",
        "xna40",
        "XNA Framework 4.0",
        "verb",
        "xna40",
        True,
    ),
    # --- XAudio / XACT ----------------------------------------------------
    (
        r"xactredist.*\.msi$",
        "xact",
        "XACT Audio runtime",
        "verb",
        "xact",
        True,
    ),
]

_COMPILED = [
    (re.compile(pattern, re.IGNORECASE), kind, desc, action, payload, recommended)
    for pattern, kind, desc, action, payload, recommended in _PATTERNS
]

# Directories we never recurse into while scanning for redists.
_SKIP_DIRS = frozenset({"uninstall", "unins", "uninst"})


def scan(install_dir: Path) -> list[RedistFinding]:
    """Walk *install_dir* recursively and return matched redistributables.

    Each file is matched against the first pattern that fits; duplicates of the
    same ``kind`` (a game ships the same vcredist in two subdirs) are collapsed.
    """
    if not install_dir.exists():
        return []

    seen_kinds: set[str] = set()
    findings: list[RedistFinding] = []

    for path in _walk_skipping(install_dir):
        if not path.is_file():
            continue
        name = path.name.lower()
        for regex, kind, desc, action, payload, recommended in _COMPILED:
            if regex.search(name):
                if kind in seen_kinds:
                    break  # already recorded for this install
                seen_kinds.add(kind)
                findings.append(
                    RedistFinding(
                        path=path,
                        kind=kind,
                        description=desc,
                        action=action,
                        payload=payload,
                        recommended=recommended,
                    )
                )
                break
    return findings


def _walk_skipping(root: Path):
    """Yield files under *root*, skipping obvious uninstall trees."""
    for entry in root.iterdir():
        if entry.is_symlink():
            continue
        if entry.is_dir():
            if entry.name.lower() in _SKIP_DIRS:
                continue
            yield from _walk_skipping(entry)
        else:
            yield entry


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


def apply_finding(
    finding: RedistFinding,
    prefix_root: Path,
    runtime: Runtime,
    on_log: Callable[[str], None] | None = None,
) -> int:
    """Execute *finding* against the given prefix.  Returns the exit code."""

    def _log(msg: str) -> None:
        if on_log:
            on_log(msg)

    if finding.action == "verb":
        _log(f"Applying winetricks verb: {finding.payload}")
        proc = run_verbs(prefix_root, [finding.payload], runtime)
        return proc.wait()
    if finding.action == "run":
        return _run_installer(finding, prefix_root, runtime, _log)
    raise ValueError(f"Unknown finding action: {finding.action}")


def _run_installer(
    finding: RedistFinding,
    prefix_root: Path,
    runtime: Runtime,
    log: Callable[[str], None],
) -> int:
    """Run a bundled installer under Wine/Proton in *prefix_root*."""
    import shlex

    extra = shlex.split(finding.payload) if finding.payload else []

    if runtime.is_proton:
        cmd = [str(runtime.path / "proton"), "run", str(finding.path), *extra]
        env = {
            "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(runtime.path.parent.parent),
            "STEAM_COMPAT_DATA_PATH": str(prefix_root),
        }
    else:
        cmd = [str(runtime.path / "bin" / "wine"), str(finding.path), *extra]
        env = {"WINEPREFIX": str(prefix_root)}

    log(f"Running: {' '.join(cmd)}")
    import os

    merged_env = {**os.environ, **env}
    proc = subprocess.Popen(
        cmd,
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip())
    return proc.wait()
