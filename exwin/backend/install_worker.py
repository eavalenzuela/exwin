"""Orchestrates the full GOG offline installer → launchable library entry pipeline."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from exwin.backend.app_config import AppConfig, save_app_config
from exwin.backend.config import Config
from exwin.backend.dxvk import install_dxvk, install_vkd3d
from exwin.backend.gog_installer import (
    app_id_from_info,
    extract,
    find_cover_art,
    find_primary_exe,
    guess_exe,
    parse_game_info,
    probe,
    validate_checksums,
)
from exwin.backend.gog_metadata import apply_metadata
from exwin.backend.prefix import create_prefix, prefix_root
from exwin.backend.runtime import Runtime
from exwin.backend.winetricks import is_available as winetricks_available
from exwin.backend.winetricks import run_verbs
from exwin.db.apps import insert_app
from exwin.models import AppEntry


def install_gog(
    installer_path: Path,
    config: Config,
    runtime: Runtime | None,
    arch: str = "win64",
    winetricks_verbs: list[str] | None = None,
    dxvk: bool = False,
    vkd3d: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> AppEntry:
    """Full GOG install pipeline.  Intended to run in a background thread.

    Steps:
        1. Probe installer (innoextract --info)
        2. Extract to apps/<app_id>/
        3. Parse goggame-*.info for exe path
        4. Copy cover art to metadata/<app_id>/cover.jpg
        5. Create Wine prefix
        6. Apply winetricks verbs (if any)
        7. Save per-app config
        8. Insert app into the library DB

    Returns the newly created AppEntry.
    """

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    # ── 0. Verify checksums (if .hashdb present) ─────────────────────────
    validate_checksums(installer_path, on_progress=_log)

    # ── 1. Probe ─────────────────────────────────────────────────────────
    _log(f"Reading installer: {installer_path.name}")
    info = probe(installer_path)
    _log(f'Found: "{info.title}" (GOG ID: {info.game_id or "unknown"})')

    app_id = app_id_from_info(info)
    install_dir = config.installs_dir / app_id

    if install_dir.exists():
        raise RuntimeError(
            f'"{info.title}" is already installed (id: {app_id}).\n'
            "Uninstall it first before reinstalling."
        )

    # ── 2. Extract ───────────────────────────────────────────────────────
    _log(f"Extracting to {install_dir} …")
    try:
        extract(installer_path, install_dir, on_progress=_log)
    except Exception as exc:
        shutil.rmtree(install_dir, ignore_errors=True)
        raise RuntimeError(f"Extraction failed: {exc}") from exc

    _log("Extraction complete.")

    # ── 3. Parse game info → exe path ────────────────────────────────────
    game_info = parse_game_info(install_dir)
    exe_path = find_primary_exe(game_info) or guess_exe(install_dir, info.title)

    # goggame-*.info stores paths relative to its own directory.  When the
    # info file lives in install_dir/game/ (GOG RAR-layout), the raw path
    # must be prefixed with "game/" to be relative to install_dir.
    if exe_path and not (install_dir / exe_path).exists():
        for subdir in ("game", "app"):
            candidate = Path(subdir) / exe_path
            if (install_dir / candidate).exists():
                exe_path = str(candidate)
                break

    if exe_path:
        _log(f"Primary executable: {exe_path}")
    else:
        _log("Warning: could not determine executable — you can set it later in app settings.")

    # ── 4. Cover art ─────────────────────────────────────────────────────
    cover_art_path = ""
    cover_src = find_cover_art(install_dir)
    if cover_src:
        meta_dir = config.metadata_dir / app_id
        meta_dir.mkdir(parents=True, exist_ok=True)
        cover_dst = meta_dir / "cover.jpg"
        shutil.copy2(cover_src, cover_dst)
        cover_art_path = str(cover_dst)
        _log(f"Cover art saved to {cover_dst.name}")
    else:
        _log("No cover art found in installer.")

    # ── 5. Create prefix ─────────────────────────────────────────────────
    _log("Creating Wine prefix …")
    p_root = (
        create_prefix(app_id, config, runtime, arch) if runtime else prefix_root(app_id, config)
    )
    if not runtime:
        p_root.mkdir(parents=True, exist_ok=True)
        _log("No runtime selected — prefix directory created (configure later).")
    else:
        _log(f"Prefix created at {p_root}")

    # ── 6. Winetricks ────────────────────────────────────────────────────
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
                f"winetricks finished (exit code {rc}){'.' if rc == 0 else ' — check logs for errors.'}"
            )

    # ── 6b. DXVK / VKD3D-Proton ──────────────────────────────────────────
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

    # ── 7. Save app config ───────────────────────────────────────────────
    app_config = AppConfig(arch=arch, winetricks_verbs=verbs, dxvk=dxvk, vkd3d=vkd3d)
    save_app_config(app_id, config, app_config)

    # ── 8. Insert into DB ────────────────────────────────────────────────
    app = AppEntry(
        app_id=app_id,
        name=info.title,
        source="gog",
        install_path=str(install_dir),
        prefix_path=str(p_root),
        exe_path=exe_path or "",
        cover_art_path=cover_art_path,
        install_date=datetime.now(UTC).isoformat(),
        runtime_id=runtime.db_id if runtime else None,
    )
    insert_app(app)

    # ── 9. GOG metadata fetch (non-fatal) ────────────────────────────────
    if info.game_id:
        try:
            apply_metadata(app_id, info.game_id, config, on_progress=_log)
        except Exception:
            _log("Metadata fetch failed — skipping.")

    _log(f'✓ "{info.title}" installed successfully.')
    return app


def install_gog_dlc(
    installer_path: Path,
    base_app: AppEntry,
    config: Config,
    runtime: Runtime | None,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Extract a GOG DLC installer into an existing game's install directory.

    Steps:
        1. Probe installer (innoextract --info) for display name
        2. Extract directly into base_app.install_path (merge, not overwrite)
        3. No prefix creation, no DB insert

    Returns the DLC title string.
    """

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    # ── 1. Probe ─────────────────────────────────────────────────────────
    _log(f"Reading DLC installer: {installer_path.name}")
    info = probe(installer_path)
    _log(f'DLC: "{info.title}"')

    # ── 2. Extract into base game directory ───────────────────────────────
    install_dir = Path(base_app.install_path)
    _log(f"Extracting DLC into {install_dir} …")
    try:
        extract(installer_path, install_dir, on_progress=_log)
    except Exception as exc:
        raise RuntimeError(f"DLC extraction failed: {exc}") from exc

    _log(f'✓ DLC "{info.title}" installed for "{base_app.name}".')
    return info.title
