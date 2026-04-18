"""Folder / portable-game import — scan a directory, pick a main exe, optionally copy.

Used by Add-Existing (folder mode) to replace the old hand-pick-an-exe flow with
point-at-a-folder + auto-detect.  Handles single-file .exe portable freeware as
the degenerate "one candidate" case.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from exwin.backend.config import Config
from exwin.backend.exe_filter import UNLIKELY_STEMS, pick_best_exe, scan_dir_for_exes


def scan_folder_for_exes(root: Path) -> list[Path]:
    """Walk *root* for candidate .exe files, filtered and ranked.

    The first entry is the heuristic best match (what :func:`pick_best_exe`
    selects); remaining entries are the rest of the candidates, sorted by the
    same "likely game binary" score so the user sees useful alternatives first.
    """
    candidates = scan_dir_for_exes(root)
    if not candidates:
        return []
    best = pick_best_exe(candidates)
    if best is None:
        return candidates
    # Promote best to front; keep the rest in a stable, interpretable order.
    rest = [c for c in candidates if c != best]
    rest.sort(key=_rank_key)
    return [best, *rest]


def _rank_key(exe: Path) -> tuple:
    """Stable sort key — cheap variant of pick_best_exe's score."""
    stem = exe.stem.lower()
    unlikely = any(w in stem for w in UNLIKELY_STEMS)
    try:
        size = exe.stat().st_size
    except OSError:
        size = 0
    return (1 if unlikely else 0, len(exe.parts), -size, exe.name.lower())


def copy_folder_into_installs(
    src: Path,
    app_id: str,
    config: Config,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Copy *src* tree into ``config.installs_dir / app_id`` and return the destination.

    Raises :class:`FileExistsError` if the destination already exists (so the
    caller can surface a clean error instead of silently merging into a prior
    install).
    """
    dest = config.installs_dir / app_id
    if dest.exists():
        raise FileExistsError(f"Install target already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if on_progress:
        on_progress(f"Copying files from {src} → {dest}…")
    shutil.copytree(src, dest, symlinks=False)
    return dest
