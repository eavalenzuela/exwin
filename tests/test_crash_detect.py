"""Tests for exwin.backend.crash_detect + Launcher crash-path integration."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from exwin.backend.app_config import AppConfig
from exwin.backend.config import Config
from exwin.backend.crash_detect import CrashInfo, build_crash_info, read_log_tail
from exwin.backend.launcher import Launcher
from exwin.backend.runtime import Runtime
from exwin.models import AppEntry, AppSource, RuntimeType

# ---------------------------------------------------------------------------
# read_log_tail / build_crash_info
# ---------------------------------------------------------------------------


class TestReadLogTail:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert read_log_tail(tmp_path / "no-such.log") == ""

    def test_returns_last_n_lines(self, tmp_path: Path) -> None:
        log = tmp_path / "a.log"
        log.write_text("\n".join(f"line {i}" for i in range(100)))
        tail = read_log_tail(log, tail_lines=10)
        assert tail.splitlines() == [f"line {i}" for i in range(90, 100)]

    def test_returns_all_when_fewer_lines(self, tmp_path: Path) -> None:
        log = tmp_path / "a.log"
        log.write_text("one\ntwo\nthree")
        assert read_log_tail(log, tail_lines=40) == "one\ntwo\nthree"

    def test_huge_log_reads_bounded(self, tmp_path: Path) -> None:
        """Only the final 64 KiB of a giant log is read — never the whole file."""
        log = tmp_path / "huge.log"
        with open(log, "w") as f:
            f.write("x" * (1024 * 1024))  # 1 MiB single line
            f.write("\nfinal line")
        tail = read_log_tail(log, tail_lines=40)
        assert len(tail) <= 64 * 1024
        assert tail.endswith("final line")

    def test_huge_log_drops_partial_first_line(self, tmp_path: Path) -> None:
        log = tmp_path / "huge.log"
        with open(log, "w") as f:
            for i in range(20000):
                f.write(f"line {i}\n")
        tail = read_log_tail(log, tail_lines=10)
        lines = tail.splitlines()
        assert lines == [f"line {i}" for i in range(19990, 20000)]


class TestBuildCrashInfo:
    def test_populates_fields(self, tmp_path: Path) -> None:
        log = tmp_path / "x.log"
        log.write_text("crash\nboom")
        app = AppEntry(app_id="a1", name="A", source=AppSource.MANUAL)
        runtime = Runtime(name="Proton 9", type=RuntimeType.PROTON, path=tmp_path, version="9.0")
        info = build_crash_info(app=app, rc=1, duration_seconds=0.5, log_path=log, runtime=runtime)
        assert info.rc == 1
        assert info.duration_seconds == 0.5
        assert info.app is app
        assert info.runtime is runtime
        assert "boom" in info.log_tail


# ---------------------------------------------------------------------------
# Launcher crash detection — drive real shell processes to avoid mocking Popen
# ---------------------------------------------------------------------------


@pytest.fixture
def sh_runtime(tmp_path: Path) -> Runtime:
    """Fake Runtime object — unused by the shell cmds we substitute."""
    return Runtime(name="Wine", type=RuntimeType.WINE, path=tmp_path / "wine", version="wine-9.0")


@pytest.fixture
def dummy_app(tmp_path: Path) -> AppEntry:
    install = tmp_path / "game"
    install.mkdir()
    (install / "Game.exe").touch()
    return AppEntry(
        app_id="crash-test",
        name="Crash Test",
        source=AppSource.MANUAL,
        install_path=install,
        prefix_path=tmp_path / "prefix",
        exe_path="Game.exe",
    )


def _wait_for_exit(launcher: Launcher, app_id: str, timeout: float = 5.0) -> None:
    """Spin until launcher no longer reports app_id as running."""
    deadline = threading.Event()
    thread = threading.Timer(timeout, deadline.set)
    thread.daemon = True
    thread.start()
    try:
        while launcher.is_running(app_id) and not deadline.is_set():
            deadline.wait(0.02)
    finally:
        thread.cancel()


def _run_with_cmd(
    launcher: Launcher,
    app: AppEntry,
    runtime: Runtime,
    cmd: list[str],
    on_exit=None,
    on_crash=None,
) -> None:
    """Launch the app with *cmd* substituted for build_command."""
    with (
        patch.object(launcher, "build_command", return_value=cmd),
        patch("exwin.backend.launcher.GLib") as mock_glib,
    ):
        mock_glib.idle_add.side_effect = lambda fn, *args: fn(*args)
        launcher.launch(
            app=app,
            runtime=runtime,
            app_config=AppConfig(),
            on_exit=on_exit,
            on_crash=on_crash,
        )
        _wait_for_exit(launcher, app.app_id)


class TestLauncherCrashDetection:
    def test_short_nonzero_fires_on_crash(
        self, tmp_config: Config, dummy_app: AppEntry, sh_runtime: Runtime
    ) -> None:
        from exwin.db.schema import init_db

        init_db(tmp_config.data_dir)
        tmp_config.crash_threshold_seconds = 5
        launcher = Launcher(tmp_config)

        crashes: list[CrashInfo] = []
        _run_with_cmd(
            launcher,
            dummy_app,
            sh_runtime,
            ["/bin/sh", "-c", "echo boom >&2; exit 17"],
            on_crash=crashes.append,
        )

        assert len(crashes) == 1
        assert crashes[0].rc == 17
        assert crashes[0].duration_seconds < 5
        assert "boom" in crashes[0].log_tail

    def test_zero_rc_does_not_fire(
        self, tmp_config: Config, dummy_app: AppEntry, sh_runtime: Runtime
    ) -> None:
        from exwin.db.schema import init_db

        init_db(tmp_config.data_dir)
        launcher = Launcher(tmp_config)

        crashes: list[CrashInfo] = []
        _run_with_cmd(
            launcher,
            dummy_app,
            sh_runtime,
            ["/bin/sh", "-c", "exit 0"],
            on_crash=crashes.append,
        )

        assert crashes == []

    def test_long_run_does_not_fire(
        self, tmp_config: Config, dummy_app: AppEntry, sh_runtime: Runtime
    ) -> None:
        from exwin.db.schema import init_db

        init_db(tmp_config.data_dir)
        # Threshold just below the sleep — normal exit time should exceed it.
        tmp_config.crash_threshold_seconds = 0
        launcher = Launcher(tmp_config)

        crashes: list[CrashInfo] = []
        _run_with_cmd(
            launcher,
            dummy_app,
            sh_runtime,
            ["/bin/sh", "-c", "exit 1"],
            on_crash=crashes.append,
        )

        assert crashes == []

    def test_user_stop_suppresses_crash(
        self, tmp_config: Config, dummy_app: AppEntry, sh_runtime: Runtime
    ) -> None:
        from exwin.db.schema import init_db

        init_db(tmp_config.data_dir)
        tmp_config.crash_threshold_seconds = 60
        launcher = Launcher(tmp_config)

        crashes: list[CrashInfo] = []

        # Kick off a sleep; stop immediately so SIGTERM sets _user_stopped.
        with (
            patch.object(
                launcher,
                "build_command",
                return_value=["/bin/sh", "-c", "sleep 30; exit 1"],
            ),
            patch("exwin.backend.launcher.GLib") as mock_glib,
        ):
            mock_glib.idle_add.side_effect = lambda fn, *args: fn(*args)
            launcher.launch(
                app=dummy_app,
                runtime=sh_runtime,
                app_config=AppConfig(),
                on_crash=crashes.append,
            )
            # Give Popen a moment to actually start before stopping.
            threading.Event().wait(0.05)
            launcher.stop(dummy_app.app_id)
            _wait_for_exit(launcher, dummy_app.app_id)

        assert crashes == []

    def test_on_exit_fires_even_on_crash(
        self, tmp_config: Config, dummy_app: AppEntry, sh_runtime: Runtime
    ) -> None:
        from exwin.db.schema import init_db

        init_db(tmp_config.data_dir)
        launcher = Launcher(tmp_config)

        exits: list[str] = []
        crashes: list[CrashInfo] = []
        _run_with_cmd(
            launcher,
            dummy_app,
            sh_runtime,
            ["/bin/sh", "-c", "exit 1"],
            on_exit=exits.append,
            on_crash=crashes.append,
        )

        assert exits == [dummy_app.app_id]
        assert len(crashes) == 1
