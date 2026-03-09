"""Save file backup/restore."""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from pathlib import Path

from exwin.backend.app_config import AppConfig
from exwin.backend.config import Config
from exwin.models import AppEntry


def _backups_dir(app_id: str, config: Config) -> Path:
    return config.data_dir / "saves" / app_id


def backup_saves(app: AppEntry, app_config: AppConfig, config: Config) -> Path:
    """Zip save_path into data_dir/saves/<id>/<timestamp>.zip. Returns zip path."""
    save_path = Path(app_config.save_path)
    if not save_path.exists():
        raise FileNotFoundError(f"Save path not found: {save_path}")
    dest_dir = _backups_dir(app.app_id, config)
    dest_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    dest = dest_dir / f"{ts}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        if save_path.is_file():
            zf.write(save_path, save_path.name)
        else:
            for f in save_path.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(save_path.parent))
    return dest


def restore_saves(backup_path: Path, app_config: AppConfig) -> None:
    """Extract backup_path zip back to save_path parent directory."""
    save_path = Path(app_config.save_path)
    dest = save_path.parent.resolve()
    with zipfile.ZipFile(backup_path, "r") as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(dest):
                raise ValueError(f"Zip path traversal blocked: {member.filename}")
        zf.extractall(dest)


def list_backups(app_id: str, config: Config) -> list[Path]:
    """Return sorted list (newest first) of backup zips."""
    dest_dir = _backups_dir(app_id, config)
    if not dest_dir.exists():
        return []
    return sorted(dest_dir.glob("*.zip"), reverse=True)
