"""Tests for exwin.backend.auto_config (auto-configure game settings)."""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from exwin.backend.app_config import AppConfig, load_app_config
from exwin.backend.auto_config import (
    apply_recommendation,
    recommend_settings,
    scan_game_hints,
)
from exwin.backend.gpu import GPU
from exwin.backend.runtime import Runtime
from exwin.models import AppEntry, AppSource, RuntimeType


def _write_pe(path: Path, machine: int = 0x8664, extra: bytes = b"") -> Path:
    e_lfanew = 0x80
    head = bytearray(e_lfanew + 24)
    head[0:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, e_lfanew)
    head[e_lfanew : e_lfanew + 4] = b"PE\x00\x00"
    struct.pack_into("<H", head, e_lfanew + 4, machine)
    path.write_bytes(bytes(head) + extra)
    return path


def _app(tmp_path: Path, exe_rel: str = "game.exe") -> AppEntry:
    return AppEntry(
        app_id="manual-testgame",
        name="Test Game",
        source=AppSource.MANUAL,
        install_path=tmp_path / "game",
        prefix_path=tmp_path / "prefix",
        exe_path=exe_rel,
    )


@pytest.fixture
def wine_rt() -> Runtime:
    return Runtime(name="Wine (wine-9.0)", type=RuntimeType.WINE, path=Path("/usr"))


@pytest.fixture
def proton_rt() -> Runtime:
    return Runtime(name="GE-Proton9-5", type=RuntimeType.PROTON, path=Path("/opt/ge9"))


# ---------------------------------------------------------------------------
# scan_game_hints
# ---------------------------------------------------------------------------


class TestScanGameHints:
    def test_missing_dir(self, tmp_path: Path) -> None:
        hints = scan_game_hints(tmp_path / "nope", "game.exe")
        assert hints.engine == ""
        assert hints.graphics == set()

    def test_dll_imports_case_insensitive(self, tmp_path: Path) -> None:
        gamedir = tmp_path / "game"
        gamedir.mkdir()
        _write_pe(gamedir / "game.exe", extra=b"...D3D11.DLL...MSVCP140.dll...mscoree.dll...")
        hints = scan_game_hints(gamedir, "game.exe")
        assert hints.graphics == {"d3d11"}
        assert hints.vc_verbs == ["vcrun2019"]
        assert hints.dotnet is True
        assert hints.exe_arch == "win64"

    def test_unity_engine(self, tmp_path: Path) -> None:
        gamedir = tmp_path / "game"
        gamedir.mkdir()
        _write_pe(gamedir / "game.exe")
        (gamedir / "UnityPlayer.dll").touch()
        hints = scan_game_hints(gamedir, "game.exe")
        assert hints.engine == "unity"
        # Unity defaults to D3D11 even when the exe reveals nothing.
        assert "d3d11" in hints.graphics

    def test_d3d12_detected(self, tmp_path: Path) -> None:
        gamedir = tmp_path / "game"
        gamedir.mkdir()
        _write_pe(gamedir / "game.exe", extra=b"\x00d3d12.dll\x00")
        hints = scan_game_hints(gamedir, "game.exe")
        assert "d3d12" in hints.graphics


# ---------------------------------------------------------------------------
# recommend_settings
# ---------------------------------------------------------------------------


class TestRecommendSettings:
    def _gamedir(self, tmp_path: Path, extra: bytes = b"") -> Path:
        gamedir = tmp_path / "game"
        gamedir.mkdir(exist_ok=True)
        _write_pe(gamedir / "game.exe", extra=extra)
        return gamedir

    def test_nvidia_enables_nvapi(self, tmp_path: Path, proton_rt) -> None:
        self._gamedir(tmp_path)
        with (
            patch(
                "exwin.backend.auto_config.detect_gpus",
                return_value=[GPU(index=0, name="NVIDIA RTX 4070", vendor="nvidia")],
            ),
            patch("exwin.backend.auto_config.vulkan_available", return_value=True),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
        ):
            rec = recommend_settings(_app(tmp_path), AppConfig(), proton_rt)
        assert rec.config.nvapi is True
        assert any(c.label.startswith("NVAPI") for c in rec.changes)

    def test_hybrid_graphics_picks_discrete(self, tmp_path: Path, proton_rt) -> None:
        self._gamedir(tmp_path)
        gpus = [
            GPU(index=0, name="Intel UHD", vendor="intel"),
            GPU(index=1, name="AMD RX 7700S", vendor="amd"),
        ]
        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=gpus),
            patch("exwin.backend.auto_config.vulkan_available", return_value=True),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
        ):
            rec = recommend_settings(_app(tmp_path), AppConfig(), proton_rt)
        assert rec.config.gpu_index == 1

    def test_proton_disables_dxvk_flag(self, tmp_path: Path, proton_rt) -> None:
        self._gamedir(tmp_path)
        current = AppConfig(dxvk=True, vkd3d=True)
        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=True),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
        ):
            rec = recommend_settings(_app(tmp_path), current, proton_rt)
        assert rec.config.dxvk is False
        assert rec.config.vkd3d is False
        assert rec.install_dxvk is False

    def test_wine_vulkan_enables_dxvk(self, tmp_path: Path, wine_rt) -> None:
        self._gamedir(tmp_path, extra=b"\x00d3d11.dll\x00")
        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=True),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
        ):
            rec = recommend_settings(_app(tmp_path), AppConfig(), wine_rt)
        assert rec.config.dxvk is True
        assert rec.install_dxvk is True

    def test_wine_d3d12_enables_vkd3d(self, tmp_path: Path, wine_rt) -> None:
        self._gamedir(tmp_path, extra=b"\x00d3d12.dll\x00")
        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=True),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
        ):
            rec = recommend_settings(_app(tmp_path), AppConfig(), wine_rt)
        assert rec.config.vkd3d is True
        assert rec.install_vkd3d is True

    def test_gamemode_when_installed(self, tmp_path: Path, proton_rt) -> None:
        self._gamedir(tmp_path)
        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=False),
            patch("exwin.backend.auto_config.shutil.which", return_value="/usr/games/gamemoderun"),
        ):
            rec = recommend_settings(_app(tmp_path), AppConfig(), proton_rt)
        assert rec.config.gamemode is True

    def test_vc_runtime_verb_from_imports(self, tmp_path: Path, proton_rt) -> None:
        self._gamedir(tmp_path, extra=b"\x00msvcp140.dll\x00")
        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=False),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
            patch("exwin.backend.auto_config.winetricks_available", return_value=True),
        ):
            rec = recommend_settings(_app(tmp_path), AppConfig(), proton_rt)
        assert "vcrun2019" in rec.new_verbs
        assert "vcrun2019" in rec.config.winetricks_verbs

    def test_existing_verb_not_duplicated(self, tmp_path: Path, proton_rt) -> None:
        self._gamedir(tmp_path, extra=b"\x00msvcp140.dll\x00")
        current = AppConfig(winetricks_verbs=["vcrun2019"])
        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=False),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
            patch("exwin.backend.auto_config.winetricks_available", return_value=True),
        ):
            rec = recommend_settings(_app(tmp_path), current, proton_rt)
        assert rec.new_verbs == []
        assert rec.config.winetricks_verbs == ["vcrun2019"]

    def test_bundled_redist_verb(self, tmp_path: Path, proton_rt) -> None:
        gamedir = self._gamedir(tmp_path)
        redist = gamedir / "_CommonRedist"
        redist.mkdir()
        (redist / "VC_redist.x64.exe").touch()
        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=False),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
            patch("exwin.backend.auto_config.winetricks_available", return_value=True),
        ):
            rec = recommend_settings(_app(tmp_path), AppConfig(), proton_rt)
        assert "vcrun2019" in rec.config.winetricks_verbs

    def test_already_configured_is_empty(self, tmp_path: Path, proton_rt) -> None:
        self._gamedir(tmp_path)
        current = AppConfig(dxvk_state_cache=True)
        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=False),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
        ):
            rec = recommend_settings(_app(tmp_path), current, proton_rt)
        assert rec.is_empty

    def test_current_config_not_mutated(self, tmp_path: Path, wine_rt) -> None:
        self._gamedir(tmp_path, extra=b"\x00msvcp140.dll\x00")
        current = AppConfig()
        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=True),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
            patch("exwin.backend.auto_config.winetricks_available", return_value=True),
        ):
            recommend_settings(_app(tmp_path), current, wine_rt)
        assert current.dxvk is False
        assert current.winetricks_verbs == []


# ---------------------------------------------------------------------------
# apply_recommendation
# ---------------------------------------------------------------------------


class TestApplyRecommendation:
    def test_saves_config(self, tmp_config, tmp_path: Path, proton_rt) -> None:
        gamedir = tmp_path / "game"
        gamedir.mkdir()
        _write_pe(gamedir / "game.exe")
        app = _app(tmp_path)
        app.prefix_path.mkdir(parents=True)

        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=False),
            patch("exwin.backend.auto_config.shutil.which", return_value="/usr/games/gamemoderun"),
        ):
            rec = recommend_settings(app, AppConfig(), proton_rt)
        assert not rec.is_empty

        problems = apply_recommendation(app, rec, tmp_config, proton_rt)
        assert problems == []
        loaded = load_app_config(app.app_id, tmp_config)
        assert loaded.gamemode is True
        assert loaded.dxvk_state_cache is True

    def test_runs_new_verbs(self, tmp_config, tmp_path: Path, proton_rt) -> None:
        gamedir = tmp_path / "game"
        gamedir.mkdir()
        _write_pe(gamedir / "game.exe", extra=b"\x00msvcp140.dll\x00")
        app = _app(tmp_path)
        app.prefix_path.mkdir(parents=True)

        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=False),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
            patch("exwin.backend.auto_config.winetricks_available", return_value=True),
        ):
            rec = recommend_settings(app, AppConfig(), proton_rt)
        assert rec.new_verbs == ["vcrun2019"]

        proc = MagicMock()
        proc.wait.return_value = 0
        with (
            patch("exwin.backend.auto_config.winetricks_available", return_value=True),
            patch("exwin.backend.auto_config.run_verbs", return_value=proc) as mock_run,
        ):
            problems = apply_recommendation(app, rec, tmp_config, proton_rt)
        assert problems == []
        mock_run.assert_called_once()
        assert mock_run.call_args[0][1] == ["vcrun2019"]

    def test_missing_prefix_reports_problem(self, tmp_config, tmp_path: Path, wine_rt) -> None:
        gamedir = tmp_path / "game"
        gamedir.mkdir()
        _write_pe(gamedir / "game.exe", extra=b"\x00d3d11.dll\x00")
        app = _app(tmp_path)
        app.prefix_path = None

        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=True),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
        ):
            rec = recommend_settings(app, AppConfig(), wine_rt)
        assert rec.install_dxvk

        problems = apply_recommendation(app, rec, tmp_config, wine_rt)
        assert any("prefix" in p.lower() for p in problems)

    def test_failed_dxvk_reported_not_raised(self, tmp_config, tmp_path: Path, wine_rt) -> None:
        gamedir = tmp_path / "game"
        gamedir.mkdir()
        _write_pe(gamedir / "game.exe", extra=b"\x00d3d11.dll\x00")
        app = _app(tmp_path)
        app.prefix_path.mkdir(parents=True)

        with (
            patch("exwin.backend.auto_config.detect_gpus", return_value=[]),
            patch("exwin.backend.auto_config.vulkan_available", return_value=True),
            patch("exwin.backend.auto_config.shutil.which", return_value=None),
        ):
            rec = recommend_settings(app, AppConfig(), wine_rt)

        with patch(
            "exwin.backend.auto_config.install_dxvk", side_effect=RuntimeError("no network")
        ):
            problems = apply_recommendation(app, rec, tmp_config, wine_rt)
        assert any("DXVK" in p for p in problems)
