"""Per-app TOML configuration stored alongside the installed game files."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

from exwin.backend.config import Config

_CONFIG_FILENAME = "app.toml"


@dataclass
class GamescopeConfig:
    """Per-app gamescope compositor settings."""

    enabled: bool = False
    output_width: int = 0  # -W; 0 = omit (native res)
    output_height: int = 0  # -H
    game_width: int = 0  # -w; internal render res
    game_height: int = 0  # -h
    fullscreen: bool = True  # -f
    upscale_filter: str = ""  # "" | "fsr" | "nis" | "linear" | "integer"
    upscale_sharpness: int = 0  # --sharpness (FSR/NIS)
    hdr: bool = False  # --hdr-enabled (needs HDR-capable gamescope build)
    frame_limit: int = 0  # -r (refresh rate / FPS cap); 0 = no cap
    mangoapp: bool = False  # --mangoapp (nested MangoHud)
    extra_args: str = ""  # raw escape hatch, shlex-split


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

    # Save file backup: absolute path to save files dir/file; empty = not configured
    save_path: str = ""

    # Gamescope compositor wrapper (HDR, FSR/NIS upscaling, frame cap)
    gamescope: GamescopeConfig = field(default_factory=GamescopeConfig)


def load_app_config(app_id: str, config: Config) -> AppConfig:
    """Load per-app config from TOML, returning defaults if the file doesn't exist."""
    path = _config_path(app_id, config)
    if not path.exists():
        return AppConfig()

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    wine = raw.get("wine", {})
    launch = raw.get("launch", {})
    backup = raw.get("backup", {})
    gs = raw.get("gamescope", {})
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
        save_path=backup.get("save_path", ""),
        gamescope=GamescopeConfig(
            enabled=gs.get("enabled", False),
            output_width=gs.get("output_width", 0),
            output_height=gs.get("output_height", 0),
            game_width=gs.get("game_width", 0),
            game_height=gs.get("game_height", 0),
            fullscreen=gs.get("fullscreen", True),
            upscale_filter=gs.get("upscale_filter", ""),
            upscale_sharpness=gs.get("upscale_sharpness", 0),
            hdr=gs.get("hdr", False),
            frame_limit=gs.get("frame_limit", 0),
            mangoapp=gs.get("mangoapp", False),
            extra_args=gs.get("extra_args", ""),
        ),
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
    if app_config.save_path:
        data["backup"] = {"save_path": app_config.save_path}

    gs = app_config.gamescope
    if gs.enabled or _gamescope_has_non_defaults(gs):
        data["gamescope"] = {
            "enabled": gs.enabled,
            "output_width": gs.output_width,
            "output_height": gs.output_height,
            "game_width": gs.game_width,
            "game_height": gs.game_height,
            "fullscreen": gs.fullscreen,
            "upscale_filter": gs.upscale_filter,
            "upscale_sharpness": gs.upscale_sharpness,
            "hdr": gs.hdr,
            "frame_limit": gs.frame_limit,
            "mangoapp": gs.mangoapp,
            "extra_args": gs.extra_args,
        }

    with open(path, "wb") as f:
        tomli_w.dump(data, f)


def _gamescope_has_non_defaults(gs: GamescopeConfig) -> bool:
    default = GamescopeConfig()
    return any(
        getattr(gs, f) != getattr(default, f)
        for f in (
            "output_width",
            "output_height",
            "game_width",
            "game_height",
            "fullscreen",
            "upscale_filter",
            "upscale_sharpness",
            "hdr",
            "frame_limit",
            "mangoapp",
            "extra_args",
        )
    )


def _config_path(app_id: str, config: Config) -> Path:
    return config.apps_dir / app_id / _CONFIG_FILENAME
