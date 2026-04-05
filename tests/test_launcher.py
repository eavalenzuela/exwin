"""Tests for exwin.backend.launcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from exwin.backend.app_config import AppConfig
from exwin.backend.config import Config
from exwin.backend.launcher import Launcher
from exwin.backend.runtime import Runtime
from exwin.models import AppEntry, AppSource, RuntimeType


@pytest.fixture
def proton_rt() -> Runtime:
    return Runtime(
        name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"), version="9.0"
    )


@pytest.fixture
def wine_rt() -> Runtime:
    return Runtime(name="Wine", type=RuntimeType.WINE, path=Path("/usr"), version="wine-9.0")


@pytest.fixture
def app(tmp_path: Path) -> AppEntry:
    install = tmp_path / "game"
    install.mkdir()
    (install / "Game.exe").touch()
    return AppEntry(
        app_id="test-app",
        name="Test Game",
        source=AppSource.MANUAL,
        install_path=install,
        prefix_path=tmp_path / "prefix",
        exe_path="Game.exe",
    )


@pytest.fixture
def launcher(tmp_config: Config) -> Launcher:
    return Launcher(tmp_config)


@pytest.fixture
def default_cfg() -> AppConfig:
    return AppConfig()


# ---------------------------------------------------------------------------
# build_command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_proton_command(
        self, launcher: Launcher, app: AppEntry, proton_rt: Runtime, default_cfg: AppConfig
    ) -> None:
        cmd = launcher.build_command(app, proton_rt, default_cfg)
        assert cmd[0] == "/opt/proton/proton"
        assert cmd[1] == "waitforexitandrun"
        assert cmd[2].endswith("Game.exe")

    def test_wine_command(
        self, launcher: Launcher, app: AppEntry, wine_rt: Runtime, default_cfg: AppConfig
    ) -> None:
        cmd = launcher.build_command(app, wine_rt, default_cfg)
        assert cmd[0] == "/usr/bin/wine"
        assert cmd[1].endswith("Game.exe")

    def test_launch_args_appended(
        self, launcher: Launcher, app: AppEntry, wine_rt: Runtime
    ) -> None:
        cfg = AppConfig(launch_args=["-windowed", "-debug"])
        cmd = launcher.build_command(app, wine_rt, cfg)
        assert "-windowed" in cmd
        assert "-debug" in cmd

    def test_gamemode_prepended(self, launcher: Launcher, app: AppEntry, wine_rt: Runtime) -> None:
        cfg = AppConfig(gamemode=True)
        with patch("exwin.backend.launcher.shutil.which", return_value="/usr/bin/gamemoderun"):
            cmd = launcher.build_command(app, wine_rt, cfg)
        assert cmd[0] == "gamemoderun"

    def test_mangohud_prepended(self, launcher: Launcher, app: AppEntry, wine_rt: Runtime) -> None:
        cfg = AppConfig(mangohud=True)
        with patch("exwin.backend.launcher.shutil.which", return_value="/usr/bin/mangohud"):
            cmd = launcher.build_command(app, wine_rt, cfg)
        assert cmd[0] == "mangohud"

    def test_raises_on_missing_exe(self, launcher: Launcher, wine_rt: Runtime) -> None:
        bad_app = AppEntry(
            app_id="bad",
            name="Bad",
            source=AppSource.MANUAL,
            install_path=Path("/nonexistent"),
            exe_path="missing.exe",
        )
        with pytest.raises(FileNotFoundError, match="Executable not found"):
            launcher.build_command(bad_app, wine_rt, AppConfig())


# ---------------------------------------------------------------------------
# build_env
# ---------------------------------------------------------------------------


class TestBuildEnv:
    def test_proton_sets_steam_compat(
        self, launcher: Launcher, app: AppEntry, proton_rt: Runtime, default_cfg: AppConfig
    ) -> None:
        env = launcher.build_env(app, proton_rt, default_cfg)
        assert env["STEAM_COMPAT_DATA_PATH"] == str(app.prefix_path)
        assert "WINEPREFIX" not in env

    def test_wine_sets_wineprefix(
        self, launcher: Launcher, app: AppEntry, wine_rt: Runtime, default_cfg: AppConfig
    ) -> None:
        env = launcher.build_env(app, wine_rt, default_cfg)
        assert env["WINEPREFIX"] == str(app.prefix_path)
        assert "STEAM_COMPAT_DATA_PATH" not in env

    def test_sets_winearch(self, launcher: Launcher, app: AppEntry, wine_rt: Runtime) -> None:
        cfg = AppConfig(arch="win32")
        env = launcher.build_env(app, wine_rt, cfg)
        assert env["WINEARCH"] == "win32"

    def test_dll_overrides(self, launcher: Launcher, app: AppEntry, wine_rt: Runtime) -> None:
        cfg = AppConfig(dll_overrides={"d3d11": "n,b"})
        env = launcher.build_env(app, wine_rt, cfg)
        assert "d3d11=n,b" in env["WINEDLLOVERRIDES"]

    def test_gpu_selection(self, launcher: Launcher, app: AppEntry, wine_rt: Runtime) -> None:
        cfg = AppConfig(gpu_index=1)
        mock_gpu = MagicMock()
        mock_gpu.name = "AMD Radeon RX 7700S"
        with patch("exwin.backend.launcher._GPUS", [MagicMock(), mock_gpu]):
            env = launcher.build_env(app, wine_rt, cfg)
        assert env["DRI_PRIME"] == "1"
        assert env["DXVK_FILTER_DEVICE_NAME"] == "AMD Radeon RX 7700S"

    def test_user_env_overrides(self, launcher: Launcher, app: AppEntry, wine_rt: Runtime) -> None:
        cfg = AppConfig(env={"CUSTOM_VAR": "hello"})
        env = launcher.build_env(app, wine_rt, cfg)
        assert env["CUSTOM_VAR"] == "hello"


# ---------------------------------------------------------------------------
# Launch / stop lifecycle
# ---------------------------------------------------------------------------


class TestLaunchLifecycle:
    def test_is_running_false_initially(self, launcher: Launcher) -> None:
        assert launcher.is_running("test-app") is False

    def test_running_ids_empty(self, launcher: Launcher) -> None:
        assert launcher.running_ids() == frozenset()

    def test_stop_noop_when_not_running(self, launcher: Launcher) -> None:
        # Should not raise
        launcher.stop("nonexistent")
