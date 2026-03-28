"""Tests for exwin.backend.prefix."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from exwin.backend.config import Config
from exwin.backend.prefix import create_prefix, delete_prefix, prefix_root, wineprefix_path
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


class TestPrefixRoot:
    def test_returns_path_under_prefixes_dir(self, tmp_config: Config) -> None:
        root = prefix_root("test-app", tmp_config)
        assert root == tmp_config.prefixes_dir / "test-app"


class TestWineprefixPath:
    def test_proton_uses_pfx_subdir(self, tmp_config: Config, proton_rt: Runtime) -> None:
        path = wineprefix_path("test-app", tmp_config, proton_rt)
        assert path == tmp_config.prefixes_dir / "test-app" / "pfx"

    def test_wine_uses_root_directly(self, tmp_config: Config, wine_rt: Runtime) -> None:
        path = wineprefix_path("test-app", tmp_config, wine_rt)
        assert path == tmp_config.prefixes_dir / "test-app"


class TestCreatePrefix:
    def test_proton_creates_dir_only(self, tmp_config: Config, proton_rt: Runtime) -> None:
        root = create_prefix("test-app", tmp_config, proton_rt)
        assert root.is_dir()
        # Proton doesn't run wineboot — just creates the directory
        assert root == tmp_config.prefixes_dir / "test-app"

    def test_wine_calls_wineboot(self, tmp_config: Config, wine_rt: Runtime) -> None:
        with patch("exwin.backend.prefix.subprocess.run") as mock_run:
            root = create_prefix("test-app", tmp_config, wine_rt, arch="win64")

        assert root.is_dir()
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert "wineboot" in args[0][0]
        assert "--init" in args[0][0]
        # Check env
        env = args[1]["env"]
        assert env["WINEPREFIX"] == str(root)
        assert env["WINEARCH"] == "win64"

    def test_wine_arch_win32(self, tmp_config: Config, wine_rt: Runtime) -> None:
        with patch("exwin.backend.prefix.subprocess.run") as mock_run:
            create_prefix("test-app", tmp_config, wine_rt, arch="win32")

        env = mock_run.call_args[1]["env"]
        assert env["WINEARCH"] == "win32"

    def test_idempotent(self, tmp_config: Config, proton_rt: Runtime) -> None:
        root1 = create_prefix("test-app", tmp_config, proton_rt)
        root2 = create_prefix("test-app", tmp_config, proton_rt)
        assert root1 == root2


class TestDeletePrefix:
    def test_removes_prefix_dir(self, tmp_config: Config) -> None:
        root = tmp_config.prefixes_dir / "test-app"
        root.mkdir(parents=True)
        (root / "pfx").mkdir()
        (root / "pfx" / "drive_c").mkdir()

        delete_prefix("test-app", tmp_config)
        assert not root.exists()

    def test_noop_when_not_exists(self, tmp_config: Config) -> None:
        # Should not raise
        delete_prefix("nonexistent-app", tmp_config)
