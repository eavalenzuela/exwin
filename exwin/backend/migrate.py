"""Move installed game data (files + Wine prefix) to the configured storage_root."""

from __future__ import annotations

import dataclasses
import shutil
from collections.abc import Callable

from exwin.backend.config import Config
from exwin.db.apps import update_paths
from exwin.models import AppEntry


def move_game_data(
    app: AppEntry,
    config: Config,
    on_progress: Callable[[str], None] | None = None,
) -> AppEntry:
    """Move *app*'s install directory and Wine prefix to the current storage locations.

    Moves:
        install_path  → config.installs_dir / app.app_id
        prefix_path   → config.prefixes_dir / app.app_id  (when separate from install)

    Updates the library DB and returns an updated :class:`AppEntry`.

    Raises :exc:`RuntimeError` if ``config.storage_root`` is not set or if a
    target directory already exists (to avoid accidental overwrites).
    """

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    if config.storage_root is None:
        raise RuntimeError("No storage root configured — set one in Settings first.")

    old_install = app.install_path
    old_prefix = app.prefix_path
    new_install = config.installs_dir / app.app_id
    new_prefix = config.prefixes_dir / app.app_id

    # ── Move install directory ────────────────────────────────────────────
    if old_install and old_install.resolve() != new_install.resolve():
        if new_install.exists():
            raise RuntimeError(
                f"Target already exists: {new_install}\nRemove it manually before migrating."
            )
        _log(f"Moving game files → {new_install} …")
        new_install.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_install), str(new_install))
        _log("Game files moved.")
        updated_install = new_install
    else:
        _log("Game files already at target location.")
        updated_install = app.install_path

    # ── Move Wine prefix ─────────────────────────────────────────────────
    # For generic installs, prefix_path == install_path (same dir, already moved).
    # For GOG installs, prefix lives in a separate directory.
    prefix_was_install = (
        old_prefix and old_install and old_prefix.resolve() == old_install.resolve()
    )

    if prefix_was_install:
        # Prefix moved together with install above; update path to match.
        updated_prefix = updated_install
    elif old_prefix and old_prefix.resolve() != new_prefix.resolve():
        if new_prefix.exists():
            raise RuntimeError(
                f"Target prefix already exists: {new_prefix}\nRemove it manually before migrating."
            )
        _log(f"Moving Wine prefix → {new_prefix} …")
        new_prefix.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_prefix), str(new_prefix))
        _log("Wine prefix moved.")
        updated_prefix = new_prefix
    else:
        _log("Wine prefix already at target location.")
        updated_prefix = app.prefix_path

    # ── Update DB ─────────────────────────────────────────────────────────
    update_paths(app.app_id, updated_install, updated_prefix)
    _log("Library database updated.")

    return dataclasses.replace(app, install_path=updated_install, prefix_path=updated_prefix)
