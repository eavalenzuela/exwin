"""Tests for exwin.backend.launcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from exwin.backend.app_config import AppConfig, GamescopeConfig
from exwin.backend.config import Config
from exwin.backend.launcher import Launcher, _build_gamescope_prefix
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


# ---------------------------------------------------------------------------
# Gamescope wrapper
# ---------------------------------------------------------------------------


def _which(name: str, available: set[str]) -> str | None:
    """Helper: fake shutil.which by whitelisting binary names."""
    return f"/usr/bin/{name}" if name in available else None


class TestGamescopePrefix:
    def test_empty_prefix_ends_with_separator(self) -> None:
        prefix = _build_gamescope_prefix(GamescopeConfig(enabled=True))
        assert prefix[0] == "gamescope"
        assert prefix[-1] == "--"

    def test_resolution_flags(self) -> None:
        prefix = _build_gamescope_prefix(
            GamescopeConfig(
                enabled=True,
                output_width=1920,
                output_height=1080,
                game_width=1280,
                game_height=720,
            )
        )
        assert "-W" in prefix and prefix[prefix.index("-W") + 1] == "1920"
        assert "-H" in prefix and prefix[prefix.index("-H") + 1] == "1080"
        assert "-w" in prefix and prefix[prefix.index("-w") + 1] == "1280"
        assert "-h" in prefix and prefix[prefix.index("-h") + 1] == "720"

    def test_upscale_and_sharpness(self) -> None:
        prefix = _build_gamescope_prefix(
            GamescopeConfig(enabled=True, upscale_filter="fsr", upscale_sharpness=7)
        )
        assert "-F" in prefix and prefix[prefix.index("-F") + 1] == "fsr"
        assert "--sharpness" in prefix and prefix[prefix.index("--sharpness") + 1] == "7"

    def test_fullscreen_and_hdr_flags(self) -> None:
        prefix = _build_gamescope_prefix(GamescopeConfig(enabled=True, fullscreen=True, hdr=True))
        assert "-f" in prefix
        assert "--hdr-enabled" in prefix

    def test_frame_limit_and_mangoapp(self) -> None:
        prefix = _build_gamescope_prefix(
            GamescopeConfig(enabled=True, frame_limit=60, mangoapp=True)
        )
        assert "-r" in prefix and prefix[prefix.index("-r") + 1] == "60"
        assert "--mangoapp" in prefix

    def test_extra_args_shlex_split(self) -> None:
        prefix = _build_gamescope_prefix(
            GamescopeConfig(enabled=True, extra_args="--force-grab-cursor --some-flag=42")
        )
        assert "--force-grab-cursor" in prefix
        assert "--some-flag=42" in prefix


class TestBuildCommandGamescope:
    def test_wraps_cmd(self, launcher: Launcher, app: AppEntry, wine_rt: Runtime) -> None:
        cfg = AppConfig(
            gamescope=GamescopeConfig(
                enabled=True, output_width=1920, output_height=1080, upscale_filter="fsr"
            )
        )
        with patch(
            "exwin.backend.launcher.shutil.which",
            side_effect=lambda n: _which(n, {"gamescope"}),
        ):
            cmd = launcher.build_command(app, wine_rt, cfg)
        assert cmd[0] == "gamescope"
        sep = cmd.index("--")
        assert cmd[sep + 1] == "/usr/bin/wine"
        assert cmd[sep + 2].endswith("Game.exe")
        assert "-W" in cmd[:sep] and "1920" in cmd[:sep]
        assert "-F" in cmd[:sep] and "fsr" in cmd[:sep]

    def test_missing_binary_leaves_cmd_unchanged(
        self, launcher: Launcher, app: AppEntry, wine_rt: Runtime
    ) -> None:
        cfg = AppConfig(gamescope=GamescopeConfig(enabled=True, output_width=1920))
        with patch("exwin.backend.launcher.shutil.which", return_value=None):
            cmd = launcher.build_command(app, wine_rt, cfg)
        assert "gamescope" not in cmd
        assert "--" not in cmd
        assert cmd[0] == "/usr/bin/wine"

    def test_disabled_does_not_wrap(
        self, launcher: Launcher, app: AppEntry, wine_rt: Runtime
    ) -> None:
        cfg = AppConfig(gamescope=GamescopeConfig(enabled=False, output_width=1920))
        with patch(
            "exwin.backend.launcher.shutil.which",
            side_effect=lambda n: _which(n, {"gamescope"}),
        ):
            cmd = launcher.build_command(app, wine_rt, cfg)
        assert "gamescope" not in cmd

    def test_mangoapp_suppresses_outer_mangohud(
        self, launcher: Launcher, app: AppEntry, wine_rt: Runtime
    ) -> None:
        cfg = AppConfig(
            mangohud=True,
            gamescope=GamescopeConfig(enabled=True, mangoapp=True),
        )
        with patch(
            "exwin.backend.launcher.shutil.which",
            side_effect=lambda n: _which(n, {"gamescope", "mangohud"}),
        ):
            cmd = launcher.build_command(app, wine_rt, cfg)
        assert cmd[0] == "gamescope"
        assert "mangohud" not in cmd
        assert "--mangoapp" in cmd[: cmd.index("--")]

    def test_mangohud_without_mangoapp_still_active(
        self, launcher: Launcher, app: AppEntry, wine_rt: Runtime
    ) -> None:
        cfg = AppConfig(
            mangohud=True,
            gamescope=GamescopeConfig(enabled=True, mangoapp=False),
        )
        with patch(
            "exwin.backend.launcher.shutil.which",
            side_effect=lambda n: _which(n, {"gamescope", "mangohud"}),
        ):
            cmd = launcher.build_command(app, wine_rt, cfg)
        assert cmd[0] == "gamescope"
        sep = cmd.index("--")
        assert cmd[sep + 1] == "mangohud"


class TestLaunchLifecycle:
    def test_is_running_false_initially(self, launcher: Launcher) -> None:
        assert launcher.is_running("test-app") is False

    def test_running_ids_empty(self, launcher: Launcher) -> None:
        assert launcher.running_ids() == frozenset()

    def test_stop_noop_when_not_running(self, launcher: Launcher) -> None:
        # Should not raise
        launcher.stop("nonexistent")


# ---------------------------------------------------------------------------
# Hook integration
# ---------------------------------------------------------------------------


class TestHookIntegration:
    def test_hooks_sequenced_pre_and_post(
        self, tmp_config: Config, app: AppEntry, wine_rt: Runtime
    ) -> None:
        """Pre-hooks run before game Popen; post-hooks after it exits."""
        from exwin.backend.app_config import HookConfig
        from exwin.db.schema import init_db

        init_db(tmp_config.data_dir)
        launcher = Launcher(tmp_config)

        events: list[str] = []

        def fake_pre(hooks, env, log):
            events.append("pre")
            from exwin.backend.hooks import HookState

            return HookState()

        def fake_post(hooks, state, rc, env, log):
            events.append("post")

        app_cfg = AppConfig(hooks=HookConfig(mount_iso="/not/real"))
        with (
            patch.object(launcher, "build_command", return_value=["/bin/true"]),
            patch("exwin.backend.launcher.apply_pre_hooks", side_effect=fake_pre),
            patch("exwin.backend.launcher.apply_post_hooks", side_effect=fake_post),
            patch("exwin.backend.launcher.GLib") as mock_glib,
        ):
            mock_glib.idle_add.side_effect = lambda fn, *args: fn(*args)

            # Wrap Popen so we can slot an event between pre and post.
            real_popen = __import__("subprocess").Popen

            def wrapped_popen(*args, **kwargs):
                events.append("popen")
                return real_popen(*args, **kwargs)

            with patch("exwin.backend.launcher.subprocess.Popen", side_effect=wrapped_popen):
                launcher.launch(app=app, runtime=wine_rt, app_config=app_cfg)
                _wait_done(launcher, app.app_id)

        assert events == ["pre", "popen", "post"]

    def test_hook_abort_synthesises_crash_and_skips_popen(
        self, tmp_config: Config, app: AppEntry, wine_rt: Runtime
    ) -> None:
        from exwin.backend.app_config import HookConfig
        from exwin.backend.crash_detect import CrashInfo
        from exwin.backend.hooks import HookAbort
        from exwin.db.schema import init_db

        init_db(tmp_config.data_dir)
        launcher = Launcher(tmp_config)

        def raising_pre(hooks, env, log):
            raise HookAbort("pre_launch_cmd exited rc=3", output="broke")

        crashes: list[CrashInfo] = []
        app_cfg = AppConfig(hooks=HookConfig(pre_launch_cmd="exit 3"))

        with (
            patch("exwin.backend.launcher.apply_pre_hooks", side_effect=raising_pre),
            patch("exwin.backend.launcher.subprocess.Popen") as mock_popen,
            patch("exwin.backend.launcher.GLib") as mock_glib,
        ):
            mock_glib.idle_add.side_effect = lambda fn, *args: fn(*args)
            launcher.launch(
                app=app,
                runtime=wine_rt,
                app_config=app_cfg,
                on_crash=crashes.append,
            )

        mock_popen.assert_not_called()
        assert len(crashes) == 1
        assert "pre_launch_cmd exited rc=3" in crashes[0].reason
        assert crashes[0].rc == -1
        assert "broke" in crashes[0].log_tail


# ---------------------------------------------------------------------------
# umu-launcher integration
# ---------------------------------------------------------------------------


class TestUmuLauncher:
    def test_umu_cmd_proton(self, launcher: Launcher, app: AppEntry, proton_rt: Runtime) -> None:
        """Proton + umu available + enabled → ``umu-run <exe>`` replaces direct proton call."""
        cfg = AppConfig()  # use_umu defaults to None → follows global (True)
        with patch("exwin.backend.umu.shutil.which", return_value="/usr/bin/umu-run"):
            cmd = launcher.build_command(app, proton_rt, cfg)
        assert cmd[0] == "umu-run"
        assert cmd[1].endswith("Game.exe")
        assert "waitforexitandrun" not in cmd

    def test_umu_disabled_falls_back(
        self, launcher: Launcher, app: AppEntry, proton_rt: Runtime
    ) -> None:
        """Global use_umu=False → direct proton even when umu installed."""
        launcher._config.use_umu = False
        cfg = AppConfig()
        with patch("exwin.backend.umu.shutil.which", return_value="/usr/bin/umu-run"):
            cmd = launcher.build_command(app, proton_rt, cfg)
        assert cmd[0] == "/opt/proton/proton"
        assert cmd[1] == "waitforexitandrun"

    def test_umu_missing_binary_falls_back(
        self, launcher: Launcher, app: AppEntry, proton_rt: Runtime
    ) -> None:
        """umu-run not on PATH → direct proton regardless of config."""
        cfg = AppConfig()
        with patch("exwin.backend.umu.shutil.which", return_value=None):
            cmd = launcher.build_command(app, proton_rt, cfg)
        assert cmd[0] == "/opt/proton/proton"

    def test_umu_wine_runtime_unchanged(
        self, launcher: Launcher, app: AppEntry, wine_rt: Runtime
    ) -> None:
        """Wine runtime is never wrapped in umu, even when installed."""
        cfg = AppConfig()
        with patch("exwin.backend.umu.shutil.which", return_value="/usr/bin/umu-run"):
            cmd = launcher.build_command(app, wine_rt, cfg)
        assert "umu-run" not in cmd
        assert cmd[0] == "/usr/bin/wine"

    def test_umu_per_app_override_off(
        self, launcher: Launcher, app: AppEntry, proton_rt: Runtime
    ) -> None:
        """Per-app use_umu=False overrides a True global."""
        launcher._config.use_umu = True
        cfg = AppConfig(use_umu=False)
        with patch("exwin.backend.umu.shutil.which", return_value="/usr/bin/umu-run"):
            cmd = launcher.build_command(app, proton_rt, cfg)
        assert cmd[0] == "/opt/proton/proton"

    def test_umu_per_app_override_on(
        self, launcher: Launcher, app: AppEntry, proton_rt: Runtime
    ) -> None:
        """Per-app use_umu=True overrides a False global."""
        launcher._config.use_umu = False
        cfg = AppConfig(use_umu=True)
        with patch("exwin.backend.umu.shutil.which", return_value="/usr/bin/umu-run"):
            cmd = launcher.build_command(app, proton_rt, cfg)
        assert cmd[0] == "umu-run"

    def test_umu_gamescope_wraps_umu(
        self, launcher: Launcher, app: AppEntry, proton_rt: Runtime
    ) -> None:
        """gamescope still prefixes the command; umu-run becomes the inner cmd."""
        cfg = AppConfig(
            gamescope=GamescopeConfig(enabled=True, output_width=1920),
        )

        def _which(name: str) -> str | None:
            return f"/usr/bin/{name}" if name in {"gamescope", "umu-run"} else None

        with (
            patch("exwin.backend.launcher.shutil.which", side_effect=_which),
            patch("exwin.backend.umu.shutil.which", side_effect=_which),
        ):
            cmd = launcher.build_command(app, proton_rt, cfg)
        assert cmd[0] == "gamescope"
        sep = cmd.index("--")
        assert cmd[sep + 1] == "umu-run"
        assert cmd[sep + 2].endswith("Game.exe")

    def test_umu_env_sets_gameid_and_protonpath(
        self, launcher: Launcher, app: AppEntry, proton_rt: Runtime
    ) -> None:
        """umu path sets GAMEID, PROTONPATH, WINEPREFIX and skips STEAM_COMPAT_*."""
        cfg = AppConfig()
        with patch("exwin.backend.umu.shutil.which", return_value="/usr/bin/umu-run"):
            env = launcher.build_env(app, proton_rt, cfg)
        assert env["GAMEID"] == "0"
        assert env["PROTONPATH"] == "/opt/proton"
        assert env["WINEPREFIX"] == str(app.prefix_path / "pfx")
        assert "STEAM_COMPAT_DATA_PATH" not in env

    def test_umu_env_uses_steam_appid_when_known(
        self, launcher: Launcher, app: AppEntry, proton_rt: Runtime
    ) -> None:
        app.steam_appid = 220
        cfg = AppConfig()
        with patch("exwin.backend.umu.shutil.which", return_value="/usr/bin/umu-run"):
            env = launcher.build_env(app, proton_rt, cfg)
        assert env["GAMEID"] == "220"


def _wait_done(launcher: Launcher, app_id: str, timeout: float = 5.0) -> None:
    import threading as _t

    deadline = _t.Event()
    t = _t.Timer(timeout, deadline.set)
    t.daemon = True
    t.start()
    try:
        while launcher.is_running(app_id) and not deadline.is_set():
            deadline.wait(0.02)
    finally:
        t.cancel()
