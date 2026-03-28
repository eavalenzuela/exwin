"""Tests for exwin.backend.winetricks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from exwin.backend.runtime import Runtime
from exwin.backend.winetricks import is_available, run_verbs
from exwin.models import RuntimeType


@pytest.fixture
def proton_rt() -> Runtime:
    return Runtime(
        name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"), version="9.0"
    )


@pytest.fixture
def wine_rt() -> Runtime:
    return Runtime(name="Wine", type=RuntimeType.WINE, path=Path("/usr"), version="wine-9.0")


class TestIsAvailable:
    def test_true_when_found(self) -> None:
        with patch("exwin.backend.winetricks.shutil.which", return_value="/usr/bin/winetricks"):
            assert is_available() is True

    def test_false_when_missing(self) -> None:
        with patch("exwin.backend.winetricks.shutil.which", return_value=None):
            assert is_available() is False


class TestRunVerbs:
    def test_raises_when_not_available(self, tmp_path: Path) -> None:
        with patch("exwin.backend.winetricks.is_available", return_value=False):
            with pytest.raises(RuntimeError, match="winetricks not found"):
                run_verbs(tmp_path, ["vcredist2019"])

    def test_raises_on_empty_verbs(self, tmp_path: Path) -> None:
        with patch("exwin.backend.winetricks.is_available", return_value=True):
            with pytest.raises(ValueError, match="No winetricks verbs"):
                run_verbs(tmp_path, [])

    def test_wine_env_setup(self, tmp_path: Path, wine_rt: Runtime) -> None:
        with (
            patch("exwin.backend.winetricks.is_available", return_value=True),
            patch("exwin.backend.winetricks.subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = MagicMock()
            run_verbs(tmp_path, ["vcredist2019"], wine_rt)

        env = mock_popen.call_args[1]["env"]
        assert env["WINEPREFIX"] == str(tmp_path)
        assert "WINE" not in env  # vanilla Wine doesn't set WINE

    def test_proton_env_setup(self, tmp_path: Path, proton_rt: Runtime) -> None:
        with (
            patch("exwin.backend.winetricks.is_available", return_value=True),
            patch("exwin.backend.winetricks.subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = MagicMock()
            run_verbs(tmp_path, ["dxvk"], proton_rt)

        env = mock_popen.call_args[1]["env"]
        assert env["WINEPREFIX"] == str(tmp_path / "pfx")
        assert env["WINE"] == "/opt/proton/files/bin/wine"
        assert env["WINE64"] == "/opt/proton/files/bin/wine64"
        assert env["WINESERVER"] == "/opt/proton/files/bin/wineserver"

    def test_unattended_flag(self, tmp_path: Path) -> None:
        with (
            patch("exwin.backend.winetricks.is_available", return_value=True),
            patch("exwin.backend.winetricks.subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = MagicMock()
            run_verbs(tmp_path, ["vcredist2019"], unattended=True)

        cmd = mock_popen.call_args[0][0]
        assert "--unattended" in cmd
        assert "vcredist2019" in cmd

    def test_no_unattended(self, tmp_path: Path) -> None:
        with (
            patch("exwin.backend.winetricks.is_available", return_value=True),
            patch("exwin.backend.winetricks.subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = MagicMock()
            run_verbs(tmp_path, ["vcredist2019"], unattended=False)

        cmd = mock_popen.call_args[0][0]
        assert "--unattended" not in cmd
