"""Per-app TOML configuration stored alongside the installed game files."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

from exwin.backend.config import Config

_CONFIG_FILENAME = "app.toml"


@dataclass
class AppConfig:
    """Runtime configuration for a single installed app."""

    # Wine prefix
    arch: str = "win64"  # "win32" | "win64"

    # Dependencies applied via winetricks at install time
    winetricks_verbs: list[str] = field(default_factory=list)

    # Extra environment variables (merged on top of the base env)
    env: dict[str, str] = field(default_factory=dict)

    # Launch options
    launch_args: list[str] = field(default_factory=list)
    gamemode: bool = False
    mangohud: bool = False

    # Wine DLL overrides — keys are DLL names, values are override types
    # e.g. {"d3d11": "n,b", "dxgi": "n,b"}
    dll_overrides: dict[str, str] = field(default_factory=dict)

    # DirectX translation layers installed into the prefix
    dxvk: bool = False
    vkd3d: bool = False

    # GPU override: DRI_PRIME index; None = system default
    gpu_index: int | None = None


def load_app_config(app_id: str, config: Config) -> AppConfig:
    """Load per-app config from TOML, returning defaults if the file doesn't exist."""
    path = _config_path(app_id, config)
    if not path.exists():
        return AppConfig()

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    wine = raw.get("wine", {})
    launch = raw.get("launch", {})
    return AppConfig(
        arch=wine.get("arch", "win64"),
        winetricks_verbs=wine.get("winetricks_verbs", []),
        env=raw.get("env", {}),
        launch_args=launch.get("args", []),
        gamemode=launch.get("gamemode", False),
        mangohud=launch.get("mangohud", False),
        dll_overrides=raw.get("dll_overrides", {}),
        dxvk=wine.get("dxvk", False),
        vkd3d=wine.get("vkd3d", False),
        gpu_index=launch.get("gpu_index"),
    )


def save_app_config(app_id: str, config: Config, app_config: AppConfig) -> None:
    """Write per-app config to TOML."""
    path = _config_path(app_id, config)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {
        "wine": {
            "arch": app_config.arch,
            "winetricks_verbs": app_config.winetricks_verbs,
            "dxvk": app_config.dxvk,
            "vkd3d": app_config.vkd3d,
        },
        "env": app_config.env,
        "launch": {
            "args": app_config.launch_args,
            "gamemode": app_config.gamemode,
            "mangohud": app_config.mangohud,
            **({"gpu_index": app_config.gpu_index} if app_config.gpu_index is not None else {}),
        },
        "dll_overrides": app_config.dll_overrides,
    }

    with open(path, "wb") as f:
        tomli_w.dump(data, f)


def _config_path(app_id: str, config: Config) -> Path:
    return config.apps_dir / app_id / _CONFIG_FILENAME
