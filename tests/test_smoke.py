"""Smoke tests — module imports and app launch validation.

UI tests (marked @pytest.mark.ui) require a working display.
Run the full suite including UI tests via:

    xvfb-run .venv/bin/pytest
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module import smoke tests (no display required)
# ---------------------------------------------------------------------------


class TestImports:
    """Verify all backend modules import without errors."""

    def test_import_config(self) -> None:
        import exwin.backend.config  # noqa: F401

    def test_import_app_config(self) -> None:
        import exwin.backend.app_config  # noqa: F401

    def test_import_gog_metadata(self) -> None:
        import exwin.backend.gog_metadata  # noqa: F401

    def test_import_gpu(self) -> None:
        import exwin.backend.gpu  # noqa: F401

    def test_import_launcher(self) -> None:
        import exwin.backend.launcher  # noqa: F401

    def test_import_runtime(self) -> None:
        import exwin.backend.runtime  # noqa: F401

    def test_import_db_schema(self) -> None:
        import exwin.db.schema  # noqa: F401

    def test_import_db_apps(self) -> None:
        import exwin.db.apps  # noqa: F401

    def test_import_models(self) -> None:
        import exwin.models  # noqa: F401

    def test_import_winetricks(self) -> None:
        import exwin.backend.winetricks  # noqa: F401

    def test_import_dxvk(self) -> None:
        import exwin.backend.dxvk  # noqa: F401

    def test_import_prefix(self) -> None:
        import exwin.backend.prefix  # noqa: F401

    def test_import_desktop_shortcut(self) -> None:
        import exwin.backend.desktop_shortcut  # noqa: F401


# ---------------------------------------------------------------------------
# App launch smoke test (requires display — skipped if $DISPLAY is unset)
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_app_launches_and_shows_window(tmp_path: Path) -> None:
    """Launch the full GTK app under Xvfb and verify it starts cleanly.

    The app is allowed to run for up to 5 seconds; after that it is killed
    (TimeoutExpired is expected and acceptable — the app has no --quit flag).
    The test fails only if a Python-level exception appears in stderr.
    """
    env = os.environ.copy()
    env["EXWIN_DATA_DIR"] = str(tmp_path / "exwin")

    proc = subprocess.Popen(
        ["xvfb-run", "--auto-servernum", sys.executable, "-m", "exwin"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid,  # own process group so we can kill all children
    )
    try:
        _stdout, stderr = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        _stdout, stderr = proc.communicate()

    assert "Traceback (most recent call last)" not in stderr, (
        f"App raised a Python exception on launch:\n{stderr}"
    )
    assert "ModuleNotFoundError" not in stderr
    assert "ImportError" not in stderr


@pytest.mark.ui
def test_env_data_dir_override(tmp_path: Path) -> None:
    """EXWIN_DATA_DIR must override the compiled-in default inside a subprocess."""
    override = tmp_path / "mydata"
    env = os.environ.copy()
    env["EXWIN_DATA_DIR"] = str(override)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            ("from exwin.backend.config import Config; cfg = Config.load(); print(cfg.data_dir)"),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert str(override) in result.stdout.strip()


@pytest.mark.ui
def test_default_data_dir_is_dot_exwin() -> None:
    """The compiled-in default must be ~/.exwin/ (no DISPLAY needed, but grouped here)."""
    from exwin.backend.config import _DEFAULT_DATA_DIR

    assert _DEFAULT_DATA_DIR == Path.home() / ".exwin"


# ---------------------------------------------------------------------------
# --launch headless mode tests (no display required)
# ---------------------------------------------------------------------------


def test_launch_flag_unknown_app_exits_nonzero(tmp_path: Path) -> None:
    """--launch <nonexistent-id> must exit with a non-zero status and print an error."""
    env = os.environ.copy()
    env["EXWIN_DATA_DIR"] = str(tmp_path / "exwin")

    result = subprocess.run(
        [sys.executable, "-m", "exwin", "--launch", "nonexistent-app-id"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "nonexistent-app-id" in result.stderr or "nonexistent-app-id" in result.stdout


def test_launch_flag_help(tmp_path: Path) -> None:
    """exwin --help must mention --launch."""
    result = subprocess.run(
        [sys.executable, "-m", "exwin", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "--launch" in result.stdout
