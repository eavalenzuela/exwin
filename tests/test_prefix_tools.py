"""Tests for exwin.backend.prefix_tools (winecfg/regedit/wineserver/wineboot -u)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from exwin.backend.prefix_tools import upgrade_prefix
from exwin.backend.runtime import Runtime
from exwin.models import RuntimeType


@pytest.fixture
def proton_rt() -> Runtime:
    return Runtime(
        name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"), version="9.0"
    )


@pytest.fixture
def wine_rt() -> Runtime:
    return Runtime(name="Wine", type=RuntimeType.WINE, path=Path("/usr"), version="wine-9.0")


class TestUpgradePrefix:
    def test_proton_invokes_proton_run_wineboot(self, tmp_path: Path, proton_rt: Runtime) -> None:
        prefix = tmp_path / "compat"
        prefix.mkdir()
        with patch("exwin.backend.prefix_tools.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            upgrade_prefix(prefix, proton_rt)

        cmd = mock_popen.call_args[0][0]
        assert cmd == ["/opt/proton/proton", "run", "wineboot", "-u"]
        env = mock_popen.call_args.kwargs["env"]
        assert env["STEAM_COMPAT_DATA_PATH"] == str(prefix)
        assert env["SteamAppId"] == "0"
        assert env["SteamGameId"] == "0"

    def test_wine_invokes_wine_wineboot(self, tmp_path: Path, wine_rt: Runtime) -> None:
        prefix = tmp_path / "wineprefix"
        prefix.mkdir()
        with patch("exwin.backend.prefix_tools.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            upgrade_prefix(prefix, wine_rt)

        cmd = mock_popen.call_args[0][0]
        assert cmd == ["/usr/bin/wine", "wineboot", "-u"]
        env = mock_popen.call_args.kwargs["env"]
        assert env["WINEPREFIX"] == str(prefix)
        assert "STEAM_COMPAT_DATA_PATH" not in env

    def test_popen_kwargs_forwarded(self, tmp_path: Path, wine_rt: Runtime) -> None:
        """stdout/stderr redirection for log-capture must reach Popen."""
        prefix = tmp_path / "wineprefix"
        prefix.mkdir()
        sentinel = object()
        with patch("exwin.backend.prefix_tools.subprocess.Popen") as mock_popen:
            upgrade_prefix(prefix, wine_rt, stdout=sentinel, stderr=sentinel)

        kw = mock_popen.call_args.kwargs
        assert kw["stdout"] is sentinel
        assert kw["stderr"] is sentinel

    def test_proton_does_not_leak_existing_steamappid_override(
        self, tmp_path: Path, proton_rt: Runtime
    ) -> None:
        """setdefault must preserve an externally-set SteamAppId (ProtonFixes hook)."""
        prefix = tmp_path / "compat"
        prefix.mkdir()
        with (
            patch("exwin.backend.prefix_tools.os.environ", {"SteamAppId": "374320"}),
            patch("exwin.backend.prefix_tools.subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = MagicMock()
            upgrade_prefix(prefix, proton_rt)
        env = mock_popen.call_args.kwargs["env"]
        assert env["SteamAppId"] == "374320"
