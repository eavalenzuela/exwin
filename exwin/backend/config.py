"""Global application configuration, stored at $data_dir/config.toml.

Default data directory: ~/.exwin/
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

_log = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path.home() / ".exwin"
_CONFIG_FILENAME = "config.toml"


def _effective_data_dir() -> Path:
    """Return the data dir, allowing EXWIN_DATA_DIR env override."""
    override = os.environ.get("EXWIN_DATA_DIR")
    return Path(override) if override else _DEFAULT_DATA_DIR


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: _DEFAULT_DATA_DIR)
    default_runtime: str = ""  # empty = auto-detect
    color_scheme: str = "system"  # "system" | "light" | "dark"
    storage_root: Path | None = None  # None = use data_dir/{apps,prefixes} (default)
    backup_max_count: int = 5  # max save backups per game (0 = unlimited)
    crash_threshold_seconds: int = 5  # short-run + non-zero rc under this → show crash dialog
    use_umu: bool = True  # use umu-launcher for Proton runtimes when available

    # Window state (restored on startup)
    window_width: int = 1100
    window_height: int = 700
    sidebar_visible: bool = True

    # ------------------------------------------------------------------ #
    # Derived paths (not stored; computed from data_dir)
    # ------------------------------------------------------------------ #

    @property
    def storage_root_available(self) -> bool:
        """True if storage_root is not set, or is set and writable."""
        return getattr(self, "_storage_root_available", True)

    @property
    def config_path(self) -> Path:
        return self.data_dir / _CONFIG_FILENAME

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def installs_dir(self) -> Path:
        """Where game files are extracted/installed. Follows storage_root when set."""
        base = self.storage_root if self.storage_root is not None else self.data_dir
        return base / "apps"

    @property
    def prefixes_dir(self) -> Path:
        """Where Wine prefixes live. Follows storage_root when set."""
        base = self.storage_root if self.storage_root is not None else self.data_dir
        return base / "prefixes"

    @property
    def apps_dir(self) -> Path:
        """Where per-app metadata (app.toml) lives. Always under data_dir."""
        return self.data_dir / "apps"

    @property
    def runtimes_dir(self) -> Path:
        return self.data_dir / "runtimes"

    @property
    def metadata_dir(self) -> Path:
        return self.data_dir / "metadata"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    # ------------------------------------------------------------------ #
    # Load / save
    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls) -> Config:
        """Load config from disk, or return defaults if not yet created.

        The data directory can be overridden via the EXWIN_DATA_DIR environment
        variable, which takes precedence over both the TOML value and the
        compiled-in default.
        """
        base_dir = _effective_data_dir()
        config_path = base_dir / _CONFIG_FILENAME
        if not config_path.exists():
            cfg = cls(data_dir=base_dir)
            cfg._ensure_dirs()
            cfg.save()
            return cfg

        with open(config_path, "rb") as f:
            raw = tomllib.load(f)

        raw_sr = raw.get("storage_root")
        win = raw.get("window", {})
        cfg = cls(
            data_dir=base_dir,  # env var always wins; TOML value is informational only
            default_runtime=raw.get("default_runtime", ""),
            color_scheme=raw.get("color_scheme", "system"),
            storage_root=Path(raw_sr) if raw_sr else None,
            backup_max_count=raw.get("backup_max_count", 5),
            crash_threshold_seconds=raw.get("crash_threshold_seconds", 5),
            use_umu=raw.get("use_umu", True),
            window_width=win.get("width", 1100),
            window_height=win.get("height", 700),
            sidebar_visible=win.get("sidebar_visible", True),
        )
        cfg._ensure_dirs()
        return cfg

    def save(self) -> None:
        """Write current config to disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data: dict = {
            "data_dir": str(self.data_dir),
            "default_runtime": self.default_runtime,
            "color_scheme": self.color_scheme,
            "backup_max_count": self.backup_max_count,
            "crash_threshold_seconds": self.crash_threshold_seconds,
            "use_umu": self.use_umu,
        }
        if self.storage_root is not None:
            data["storage_root"] = str(self.storage_root)
        data["window"] = {
            "width": self.window_width,
            "height": self.window_height,
            "sidebar_visible": self.sidebar_visible,
        }
        with open(self.config_path, "wb") as f:
            tomli_w.dump(data, f)

    def _ensure_dirs(self) -> None:
        # Dirs that must always exist (under data_dir)
        for d in (
            self.data_dir,
            self.apps_dir,
            self.runtimes_dir,
            self.metadata_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        # Storage-root dirs may be on an external drive; warn if unavailable
        self._storage_root_available = True
        if self.storage_root is not None:
            for d in (self.installs_dir, self.prefixes_dir):
                try:
                    d.mkdir(parents=True, exist_ok=True)
                except OSError:
                    self._storage_root_available = False
                    _log.warning(
                        "Storage root directory '%s' is not writable — "
                        "external drive may be unmounted. Installs and launches "
                        "that depend on it will fail.",
                        d,
                    )
        else:
            for d in (self.installs_dir, self.prefixes_dir):
                d.mkdir(parents=True, exist_ok=True)
