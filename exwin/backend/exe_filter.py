"""Shared heuristics for identifying a game's main executable.

Used by both the Wine-prefix-based installer path (generic_installer) and the
archive-extraction path (archive_installer).  Drive-C-specific filtering
(e.g. skipping ``windows/`` or fake Steam installs) lives with the caller.
"""

from __future__ import annotations

from pathlib import Path

# Directory basenames to skip when scanning for candidate exes.
# Applied as substring matches against the full lowercased path.
SKIP_DIRS = {
    "__redist",
    "unins",
    "uninstall",
    "setup",
    "vcredist",
    "dotnet",
    "isisetup",
}

# Exact filenames to skip (case-insensitive).
SKIP_EXE_NAMES = {
    "unins000.exe",
    "uninst.exe",
    "uninstall.exe",
    "setup.exe",
    "instmsia.exe",  # MSI 2.0 runtime bootstrapper shipped inside older installers
    "instmsiw.exe",
}

# Words in a stem that suggest a non-game executable.
UNLIKELY_STEMS = {
    "server",
    "launcher",
    "updater",
    "patcher",
    "config",
    "settings",
    "crash",
    "bugreport",
    "report",
    "helper",
}


def should_skip(exe: Path) -> bool:
    """Return True if *exe* looks like an installer/uninstaller/redist artefact."""
    if exe.name.lower() in SKIP_EXE_NAMES:
        return True
    lowered = str(exe).lower()
    return any(skip in lowered for skip in SKIP_DIRS)


def pick_best_exe(candidates: list[Path]) -> Path | None:
    """Heuristically select the most likely main executable from a filtered list."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    def _score(exe: Path) -> tuple:
        stem_lower = exe.stem.lower()
        unlikely = any(word in stem_lower for word in UNLIKELY_STEMS)
        depth = len(exe.parts)
        try:
            size = exe.stat().st_size
        except OSError:
            size = 0
        # lower is better: penalise unlikely names, prefer shallower, prefer larger
        return (1 if unlikely else 0, depth, -size)

    return min(candidates, key=_score)


def scan_dir_for_exes(root: Path) -> list[Path]:
    """Walk *root* recursively for .exe files, skipping installers/uninstallers.

    Results are sorted shallowest-first, then by filename.  Unlike
    :func:`generic_installer.scan_candidate_exes` this does not apply
    drive-C-specific filtering — use it on plain archive extractions.
    """
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for exe in root.rglob("*.exe"):
        if should_skip(exe):
            continue
        candidates.append(exe)
    return sorted(candidates, key=lambda p: (len(p.parts), p.name.lower()))
