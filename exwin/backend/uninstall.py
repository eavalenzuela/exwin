"""Shared uninstall logic for both GUI and CLI."""

from __future__ import annotations

import shutil
from collections.abc import Callable

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
        if app.install_path and app.install_path.exists():
            shutil.rmtree(app.install_path, ignore_errors=True)
            _log(f"Deleted: {app.install_path}")
        if app.prefix_path and app.prefix_path != app.install_path and app.prefix_path.exists():
            shutil.rmtree(app.prefix_path, ignore_errors=True)
            _log(f"Deleted: {app.prefix_path}")

    metadata_dir = config.metadata_dir / app.app_id
    shutil.rmtree(metadata_dir, ignore_errors=True)
    _log(f"Deleted metadata: {metadata_dir}")

    apps_dir = config.apps_dir / app.app_id
    shutil.rmtree(apps_dir, ignore_errors=True)
    _log(f"Deleted config: {apps_dir}")

    delete_app(app.app_id)
    _log(f'"{app.name}" removed from library.')
