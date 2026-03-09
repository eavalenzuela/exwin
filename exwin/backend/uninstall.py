"""Shared uninstall logic for both GUI and CLI."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from exwin.backend.config import Config
from exwin.db.apps import delete_app
from exwin.models import AppEntry


def uninstall_app(
    app: AppEntry,
    config: Config,
    delete_files: bool,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Remove an app from the library and optionally delete its files.

    Steps:
        1. Delete install_path and prefix_path (if delete_files=True)
        2. Delete metadata directory (cover art, etc.)
        3. Delete per-app config directory (app.toml)
        4. Remove the DB entry
    """

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    if delete_files:
        install = Path(app.install_path) if app.install_path else None
        prefix = Path(app.prefix_path) if app.prefix_path else None
        if install and install.exists():
            shutil.rmtree(install, ignore_errors=True)
            _log(f"Deleted: {install}")
        if prefix and prefix != install and prefix.exists():
            shutil.rmtree(prefix, ignore_errors=True)
            _log(f"Deleted: {prefix}")

    metadata_dir = config.metadata_dir / app.app_id
    shutil.rmtree(metadata_dir, ignore_errors=True)
    _log(f"Deleted metadata: {metadata_dir}")

    apps_dir = config.apps_dir / app.app_id
    shutil.rmtree(apps_dir, ignore_errors=True)
    _log(f"Deleted config: {apps_dir}")

    delete_app(app.app_id)
    _log(f'"{app.name}" removed from library.')
