"""Tests for exwin.backend.app_config (per-app TOML configuration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from exwin.backend.app_config import AppConfig, GamescopeConfig, load_app_config, save_app_config
from exwin.backend.config import Config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    c = Config(data_dir=tmp_path / "exwin")
    c._ensure_dirs()
    return c


# ---------------------------------------------------------------------------
# Defaults when no file exists
# ---------------------------------------------------------------------------


class TestLoadDefaults:
    def test_returns_defaults_when_missing(self, cfg: Config) -> None:
        ac = load_app_config("no-such-app", cfg)
        assert ac.arch == "win64"
        assert ac.winetricks_verbs == []
        assert ac.env == {}
        assert ac.launch_args == []
        assert ac.gamemode is False
        assert ac.mangohud is False
        assert ac.dll_overrides == {}
        assert ac.dxvk is False
        assert ac.vkd3d is False
        assert ac.gpu_index is None
        assert ac.gamescope.enabled is False
        assert ac.gamescope.fullscreen is True
        assert ac.gamescope.output_width == 0
        assert ac.gamescope.upscale_filter == ""


# ---------------------------------------------------------------------------
# Round-trip save / load
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def _save_load(self, cfg: Config, ac: AppConfig) -> AppConfig:
        save_app_config("myapp", cfg, ac)
        return load_app_config("myapp", cfg)

    def test_arch_win32(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(arch="win32"))
        assert loaded.arch == "win32"

    def test_winetricks_verbs(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(winetricks_verbs=["vcredist2019", "dxvk"]))
        assert loaded.winetricks_verbs == ["vcredist2019", "dxvk"]

    def test_env_vars(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(env={"WINEDEBUG": "-all", "FOO": "bar"}))
        assert loaded.env == {"WINEDEBUG": "-all", "FOO": "bar"}

    def test_launch_args(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(launch_args=["-nosound", "-window"]))
        assert loaded.launch_args == ["-nosound", "-window"]

    def test_gamemode(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(gamemode=True))
        assert loaded.gamemode is True

    def test_mangohud(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(mangohud=True))
        assert loaded.mangohud is True

    def test_dll_overrides(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(dll_overrides={"d3d11": "n,b", "dxgi": "n,b"}))
        assert loaded.dll_overrides == {"d3d11": "n,b", "dxgi": "n,b"}

    def test_dxvk(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(dxvk=True))
        assert loaded.dxvk is True

    def test_vkd3d(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(vkd3d=True))
        assert loaded.vkd3d is True

    def test_gpu_index_zero(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(gpu_index=0))
        assert loaded.gpu_index == 0

    def test_gpu_index_positive(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(gpu_index=2))
        assert loaded.gpu_index == 2

    def test_gpu_index_none(self, cfg: Config) -> None:
        loaded = self._save_load(cfg, AppConfig(gpu_index=None))
        assert loaded.gpu_index is None

    def test_all_fields_together(self, cfg: Config) -> None:
        ac = AppConfig(
            arch="win32",
            winetricks_verbs=["vcredist2019"],
            env={"WINEDEBUG": "-all"},
            launch_args=["-nosound"],
            gamemode=True,
            mangohud=True,
            dll_overrides={"d3d11": "n,b"},
            dxvk=True,
            vkd3d=True,
            gpu_index=1,
        )
        loaded = self._save_load(cfg, ac)
        assert loaded.arch == "win32"
        assert loaded.winetricks_verbs == ["vcredist2019"]
        assert loaded.env == {"WINEDEBUG": "-all"}
        assert loaded.launch_args == ["-nosound"]
        assert loaded.gamemode is True
        assert loaded.mangohud is True
        assert loaded.dll_overrides == {"d3d11": "n,b"}
        assert loaded.dxvk is True
        assert loaded.vkd3d is True
        assert loaded.gpu_index == 1

    def test_creates_app_subdir(self, cfg: Config) -> None:
        save_app_config("myapp", cfg, AppConfig())
        assert (cfg.apps_dir / "myapp" / "app.toml").exists()


# ---------------------------------------------------------------------------
# Gamescope config round-trip
# ---------------------------------------------------------------------------


class TestGamescopeRoundTrip:
    def _save_load(self, cfg: Config, ac: AppConfig) -> AppConfig:
        save_app_config("myapp", cfg, ac)
        return load_app_config("myapp", cfg)

    def test_disabled_default_not_written(self, cfg: Config) -> None:
        save_app_config("myapp", cfg, AppConfig())
        toml_text = (cfg.apps_dir / "myapp" / "app.toml").read_text()
        assert "[gamescope]" not in toml_text

    def test_enabled_round_trip(self, cfg: Config) -> None:
        gs = GamescopeConfig(
            enabled=True,
            output_width=1920,
            output_height=1080,
            game_width=1280,
            game_height=720,
            fullscreen=False,
            upscale_filter="fsr",
            upscale_sharpness=5,
            hdr=True,
            frame_limit=60,
            mangoapp=True,
            extra_args="--force-grab-cursor",
        )
        loaded = self._save_load(cfg, AppConfig(gamescope=gs))
        assert loaded.gamescope.enabled is True
        assert loaded.gamescope.output_width == 1920
        assert loaded.gamescope.output_height == 1080
        assert loaded.gamescope.game_width == 1280
        assert loaded.gamescope.game_height == 720
        assert loaded.gamescope.fullscreen is False
        assert loaded.gamescope.upscale_filter == "fsr"
        assert loaded.gamescope.upscale_sharpness == 5
        assert loaded.gamescope.hdr is True
        assert loaded.gamescope.frame_limit == 60
        assert loaded.gamescope.mangoapp is True
        assert loaded.gamescope.extra_args == "--force-grab-cursor"

    def test_non_default_disabled_is_persisted(self, cfg: Config) -> None:
        # User tweaked fields then flipped enabled off — values must survive.
        gs = GamescopeConfig(enabled=False, output_width=2560, upscale_filter="nis")
        loaded = self._save_load(cfg, AppConfig(gamescope=gs))
        assert loaded.gamescope.enabled is False
        assert loaded.gamescope.output_width == 2560
        assert loaded.gamescope.upscale_filter == "nis"
