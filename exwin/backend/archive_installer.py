"""Detection and extraction for archive-based game installers (zip/7z/rar).

Unlike GOG InnoSetup installers or generic Wine-installed ``.exe`` files,
archives are extracted directly to an app directory — no Wine installer
runs.  After extraction the caller picks a main executable, creates a Wine
prefix, and registers the app.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from exwin.backend.app_config import AppConfig, save_app_config
from exwin.backend.config import Config
from exwin.backend.dxvk import install_dxvk, install_vkd3d
from exwin.backend.exe_filter import scan_dir_for_exes
from exwin.backend.prefix import create_prefix, prefix_root
from exwin.backend.runtime import Runtime
from exwin.backend.winetricks import is_available as winetricks_available
from exwin.backend.winetricks import run_verbs
from exwin.db.apps import insert_app
from exwin.models import AppEntry, AppSource

# Archive header magic bytes.
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_7Z_MAGIC = b"7z\xbc\xaf\x27\x1c"
_RAR_MAGIC = b"Rar!\x1a\x07"


# ---------------------------------------------------------------------------
# Detection & tool discovery
# ---------------------------------------------------------------------------


def detect_archive_type(path: Path) -> str | None:
    """Sniff the file header and return ``"zip"``, ``"7z"``, ``"rar"``, or None."""
    try:
        with open(path, "rb") as f:
            header = f.read(8)
    except OSError:
        return None
    if any(header.startswith(m) for m in _ZIP_MAGICS):
        return "zip"
    if header.startswith(_7Z_MAGIC):
        return "7z"
    if header.startswith(_RAR_MAGIC):
        return "rar"
    return None


def _find_7z() -> str | None:
    for name in ("7z", "7zz", "7za"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _find_rar_tool() -> str | None:
    for name in ("unar", "unrar"):
        path = shutil.which(name)
        if path:
            return path
    return None


def archive_tool_available(kind: str) -> bool:
    """Return True if the extraction tool for *kind* is on PATH."""
    if kind == "zip":
        return True  # stdlib
    if kind == "7z":
        return _find_7z() is not None
    if kind == "rar":
        return _find_rar_tool() is not None
    return False


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def count_archive_members(path: Path) -> int:
    """Return the number of files in the archive, or 0 if unknown."""
    kind = detect_archive_type(path)
    if kind == "zip":
        try:
            with zipfile.ZipFile(path) as zf:
                return sum(1 for info in zf.infolist() if not info.is_dir())
        except zipfile.BadZipFile:
            return 0
    if kind == "7z":
        tool = _find_7z()
        if not tool:
            return 0
        try:
            result = subprocess.run(
                [tool, "l", "-slt", "-ba", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return 0
        # -slt prints one "Path = …" line per member (-ba suppresses headers).
        return result.stdout.count("\nPath = ") + (1 if result.stdout.startswith("Path = ") else 0)
    if kind == "rar":
        tool = _find_rar_tool()
        if not tool:
            return 0
        try:
            result = subprocess.run(
                [tool, "-l", str(path)], capture_output=True, text=True, timeout=30
            )
        except (subprocess.TimeoutExpired, OSError):
            return 0
        match = re.search(r"contains\s+(\d+)\s+file", result.stdout)
        if match:
            return int(match.group(1))
        return 0
    return 0


def extract_archive(
    src: Path,
    dest: Path,
    on_progress: Callable[[str], None] | None = None,
    on_file_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Extract *src* into *dest* using the appropriate backend.

    Raises RuntimeError for unknown formats or missing tools.
    """

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    dest.mkdir(parents=True, exist_ok=True)
    kind = detect_archive_type(src)

    if kind == "zip":
        _extract_zip(src, dest, _log, on_file_progress)
    elif kind == "7z":
        _extract_7z(src, dest, _log, on_file_progress)
    elif kind == "rar":
        _extract_rar(src, dest, _log, on_file_progress)
    else:
        raise RuntimeError(f"Unknown archive format: {src}")


def _extract_zip(src, dest, log, on_file_progress):
    with zipfile.ZipFile(src) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        total = len(members)
        log(f"Extracting {total} files from {src.name} …")
        for idx, member in enumerate(members, 1):
            zf.extract(member, dest)
            if on_file_progress:
                on_file_progress(idx, total)


def _extract_7z(src, dest, log, on_file_progress):
    tool = _find_7z()
    if not tool:
        raise RuntimeError("7z not found — install p7zip-full")
    total = count_archive_members(src)
    log(f"Extracting {src.name} via {Path(tool).name} …")
    proc = subprocess.Popen(
        [tool, "x", f"-o{dest}", "-y", "-bb1", str(src)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    count = 0
    assert proc.stdout is not None
    for line in proc.stdout:
        # With -bb1, 7z emits "- <path>" lines as it extracts.
        if line.startswith("- "):
            count += 1
            if on_file_progress and total:
                on_file_progress(count, total)
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"7z exited with code {rc}")


def _extract_rar(src, dest, log, on_file_progress):
    tool = _find_rar_tool()
    if not tool:
        raise RuntimeError("No RAR tool found — install 'unar' or 'unrar'")
    total = count_archive_members(src)
    tool_name = Path(tool).name
    log(f"Extracting {src.name} via {tool_name} …")
    if tool_name == "unar":
        cmd = [tool, "-o", str(dest), "-f", str(src)]
    else:
        # unrar x <archive> <dest-with-trailing-sep>
        cmd = [tool, "x", "-y", str(src), str(dest) + os.sep]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    count = 0
    assert proc.stdout is not None
    for line in proc.stdout:
        if tool_name == "unar":
            stripped = line.strip()
            if stripped and not stripped.lower().startswith("successfully"):
                count += 1
        else:
            if line.lstrip().startswith("Extracting"):
                count += 1
        if on_file_progress and total:
            on_file_progress(count, total)
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"RAR extraction failed with code {rc}")


def flatten_single_toplevel(install_dir: Path) -> None:
    """If *install_dir* holds exactly one nested directory, lift its contents up.

    Archives commonly wrap the game in a single ``<GameName>/`` folder; this
    removes that indirection so ``install_path`` points directly at the game.
    """
    entries = list(install_dir.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        return
    nested = entries[0]
    for child in list(nested.iterdir()):
        shutil.move(str(child), str(install_dir / child.name))
    nested.rmdir()


# ---------------------------------------------------------------------------
# Install pipeline
# ---------------------------------------------------------------------------


def slugify_app_id(name: str) -> str:
    slug = re.sub(r"\W+", "-", name.lower()).strip("-")
    return f"archive-{slug}" if slug else "archive-unnamed"


def install_archive(
    installer_path: Path,
    app_name: str,
    config: Config,
    on_progress: Callable[[str], None] | None = None,
    on_file_progress: Callable[[int, int], None] | None = None,
) -> tuple[Path, list[Path]]:
    """Extract *installer_path* into a fresh app dir and return the candidate exes.

    Returns ``(install_dir, exe_candidates)`` — the caller picks a main exe
    (interactively if >1) and calls :func:`finalize_archive_install` to set
    up the Wine prefix and persist the app.
    """

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    app_id = slugify_app_id(app_name)
    install_dir = config.installs_dir / app_id

    if install_dir.exists():
        raise RuntimeError(
            f'"{app_name}" is already installed (id: {app_id}).\n'
            "Uninstall it first before reinstalling."
        )

    _log(f"Extracting to {install_dir} …")
    try:
        extract_archive(
            installer_path, install_dir, on_progress=_log, on_file_progress=on_file_progress
        )
    except Exception:
        shutil.rmtree(install_dir, ignore_errors=True)
        raise

    flatten_single_toplevel(install_dir)
    _log("Extraction complete.")

    candidates = scan_dir_for_exes(install_dir)
    if not candidates:
        _log("Warning: no executables found in archive.")
    return install_dir, candidates


def finalize_archive_install(
    app_name: str,
    install_dir: Path,
    exe_abs: Path,
    config: Config,
    runtime: Runtime | None,
    arch: str = "win64",
    winetricks_verbs: list[str] | None = None,
    dxvk: bool = False,
    vkd3d: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> AppEntry:
    """Create the prefix, apply winetricks/DXVK/VKD3D, save config, insert in DB."""

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    app_id = slugify_app_id(app_name)

    _log("Creating Wine prefix …")
    p_root = (
        create_prefix(app_id, config, runtime, arch) if runtime else prefix_root(app_id, config)
    )
    if not runtime:
        p_root.mkdir(parents=True, exist_ok=True)
        _log("No runtime selected — prefix directory created (configure later).")
    else:
        _log(f"Prefix created at {p_root}")

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

    if dxvk:
        _log("Installing DXVK…")
        try:
            install_dxvk(p_root, runtime, on_progress=_log)
        except Exception as exc:
            _log(f"DXVK install failed: {exc}")

    if vkd3d:
        _log("Installing vkd3d-proton…")
        try:
            install_vkd3d(p_root, runtime, on_progress=_log)
        except Exception as exc:
            _log(f"vkd3d-proton install failed: {exc}")

    app_config = AppConfig(arch=arch, winetricks_verbs=verbs, dxvk=dxvk, vkd3d=vkd3d)
    save_app_config(app_id, config, app_config)

    try:
        exe_rel = str(exe_abs.relative_to(install_dir))
    except ValueError:
        exe_rel = str(exe_abs)

    app = AppEntry(
        app_id=app_id,
        name=app_name,
        source=AppSource.MANUAL,
        install_path=install_dir,
        prefix_path=p_root,
        exe_path=exe_rel,
        cover_art_path=None,
        install_date=datetime.now(UTC).isoformat(),
        runtime_id=runtime.db_id if runtime else None,
    )
    insert_app(app)
    _log(f'✓ "{app_name}" added to library.')
    return app
