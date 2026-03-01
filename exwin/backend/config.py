"""Global application configuration, stored at $data_dir/config.toml.

Default data directory: ~/.exwin/
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

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
    prefix_root: Path | None = None  # None = use data_dir/prefixes (default)

    # ------------------------------------------------------------------ #
    # Derived paths (not stored; computed from data_dir)
    # ------------------------------------------------------------------ #

    @property
    def config_path(self) -> Path:
        return self.data_dir / _CONFIG_FILENAME

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def prefixes_dir(self) -> Path:
        return self.prefix_root if self.prefix_root is not None else self.data_dir / "prefixes"

    @property
    def apps_dir(self) -> Path:
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

        raw_pr = raw.get("prefix_root")
        cfg = cls(
            data_dir=base_dir,  # env var always wins; TOML value is informational only
            default_runtime=raw.get("default_runtime", ""),
            color_scheme=raw.get("color_scheme", "system"),
            prefix_root=Path(raw_pr) if raw_pr else None,
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
        }
        if self.prefix_root is not None:
            data["prefix_root"] = str(self.prefix_root)
        with open(self.config_path, "wb") as f:
            tomli_w.dump(data, f)

    def _ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.prefixes_dir,
            self.apps_dir,
            self.runtimes_dir,
            self.metadata_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
