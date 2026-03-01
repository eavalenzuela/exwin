"""Global application configuration, stored at $data_dir/config.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

_DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "exwin"
_CONFIG_FILENAME = "config.toml"


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: _DEFAULT_DATA_DIR)
    default_runtime: str = ""  # empty = auto-detect
    color_scheme: str = "system"  # "system" | "light" | "dark"

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
        return self.data_dir / "prefixes"

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
        """Load config from disk, or return defaults if not yet created."""
        config_path = _DEFAULT_DATA_DIR / _CONFIG_FILENAME
        if not config_path.exists():
            cfg = cls()
            cfg._ensure_dirs()
            cfg.save()
            return cfg

        with open(config_path, "rb") as f:
            raw = tomllib.load(f)

        cfg = cls(
            data_dir=Path(raw.get("data_dir", _DEFAULT_DATA_DIR)),
            default_runtime=raw.get("default_runtime", ""),
            color_scheme=raw.get("color_scheme", "system"),
        )
        cfg._ensure_dirs()
        return cfg

    def save(self) -> None:
        """Write current config to disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "data_dir": str(self.data_dir),
            "default_runtime": self.default_runtime,
            "color_scheme": self.color_scheme,
        }
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
