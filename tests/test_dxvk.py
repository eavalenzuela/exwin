"""Tests for exwin.backend.dxvk."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from exwin.backend.dxvk import (
    _find_setup_script,
    _find_tarball_asset,
    install_dxvk,
    install_vkd3d,
)
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


# ---------------------------------------------------------------------------
# install_dxvk
# ---------------------------------------------------------------------------


class TestInstallDxvk:
    def test_raises_when_winetricks_missing(self, tmp_path: Path) -> None:
        with patch("exwin.backend.dxvk.winetricks_available", return_value=False):
            with pytest.raises(RuntimeError, match="winetricks is required"):
                install_dxvk(tmp_path, None)

    def test_calls_winetricks_dxvk(self, tmp_path: Path, wine_rt: Runtime) -> None:
        mock_proc = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with (
            patch("exwin.backend.dxvk.winetricks_available", return_value=True),
            patch("exwin.backend.dxvk.run_verbs", return_value=mock_proc) as mock_run,
        ):
            install_dxvk(tmp_path, wine_rt)

        mock_run.assert_called_once_with(tmp_path, ["dxvk"], wine_rt)

    def test_raises_on_failure(self, tmp_path: Path, wine_rt: Runtime) -> None:
        mock_proc = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1

        with (
            patch("exwin.backend.dxvk.winetricks_available", return_value=True),
            patch("exwin.backend.dxvk.run_verbs", return_value=mock_proc),
        ):
            with pytest.raises(RuntimeError, match="winetricks dxvk failed"):
                install_dxvk(tmp_path, wine_rt)

    def test_progress_callback(self, tmp_path: Path) -> None:
        mock_proc = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        messages = []

        with (
            patch("exwin.backend.dxvk.winetricks_available", return_value=True),
            patch("exwin.backend.dxvk.run_verbs", return_value=mock_proc),
        ):
            install_dxvk(tmp_path, None, on_progress=messages.append)

        assert any("DXVK" in m for m in messages)


# ---------------------------------------------------------------------------
# _find_tarball_asset
# ---------------------------------------------------------------------------


class TestFindTarballAsset:
    def test_finds_tar_gz(self) -> None:
        release = {
            "assets": [
                {"name": "checksums.txt"},
                {"name": "vkd3d-proton-2.13.tar.gz", "browser_download_url": "https://..."},
            ]
        }
        asset = _find_tarball_asset(release)
        assert asset["name"] == "vkd3d-proton-2.13.tar.gz"

    def test_finds_tar_zst(self) -> None:
        release = {
            "assets": [
                {"name": "vkd3d-proton-2.13.tar.zst", "browser_download_url": "https://..."},
            ]
        }
        asset = _find_tarball_asset(release)
        assert asset["name"].endswith(".tar.zst")

    def test_raises_when_no_tarball(self) -> None:
        release = {"assets": [{"name": "README.md"}]}
        with pytest.raises(RuntimeError, match="No tarball asset"):
            _find_tarball_asset(release)


# ---------------------------------------------------------------------------
# _find_setup_script
# ---------------------------------------------------------------------------


class TestFindSetupScript:
    def test_finds_script(self, tmp_path: Path) -> None:
        sub = tmp_path / "vkd3d-proton-2.13"
        sub.mkdir()
        script = sub / "setup_vkd3d_proton.sh"
        script.touch()
        assert _find_setup_script(tmp_path) == script

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert _find_setup_script(tmp_path) is None


# ---------------------------------------------------------------------------
# install_vkd3d
# ---------------------------------------------------------------------------


class TestInstallVkd3d:
    def test_falls_back_to_winetricks(self, tmp_path: Path, wine_rt: Runtime) -> None:
        """When GitHub API fails, should fall back to winetricks."""
        mock_proc = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with (
            patch(
                "exwin.backend.dxvk._get_latest_vkd3d_release", side_effect=Exception("API error")
            ),
            patch("exwin.backend.dxvk.winetricks_available", return_value=True),
            patch("exwin.backend.dxvk.run_verbs", return_value=mock_proc) as mock_run,
        ):
            install_vkd3d(tmp_path, wine_rt)

        mock_run.assert_called_once_with(tmp_path, ["vkd3d_proton"], wine_rt)

    def test_raises_when_both_paths_fail(self, tmp_path: Path) -> None:
        with (
            patch("exwin.backend.dxvk._get_latest_vkd3d_release", side_effect=Exception("API")),
            patch("exwin.backend.dxvk.winetricks_available", return_value=False),
        ):
            with pytest.raises(RuntimeError, match="winetricks is required"):
                install_vkd3d(tmp_path, None)
