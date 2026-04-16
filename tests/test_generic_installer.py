"""Tests for exwin.backend.generic_installer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from exwin.backend.generic_installer import (
    _slugify_app_id,
    detect_installer_type,
    pick_best_exe,
    run_wine_installer,
    scan_candidate_exes,
)
from exwin.backend.runtime import Runtime
from exwin.models import RuntimeType


@pytest.fixture
def wine_rt() -> Runtime:
    return Runtime(name="Wine", type=RuntimeType.WINE, path=Path("/usr"), version="wine-9.0")


@pytest.fixture
def proton_rt() -> Runtime:
    return Runtime(
        name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"), version="9.0"
    )


# ---------------------------------------------------------------------------
# detect_installer_type
# ---------------------------------------------------------------------------


class TestDetectInstallerType:
    def test_innosetup_detected(self, tmp_path: Path) -> None:
        exe = tmp_path / "setup.exe"
        exe.touch()
        with (
            patch(
                "exwin.backend.generic_installer.find_innoextract",
                return_value="/usr/bin/innoextract",
            ),
            patch("exwin.backend.generic_installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            assert detect_installer_type(exe) == "innosetup"

    def test_generic_when_innoextract_fails(self, tmp_path: Path) -> None:
        exe = tmp_path / "setup.exe"
        exe.touch()
        with (
            patch(
                "exwin.backend.generic_installer.find_innoextract",
                return_value="/usr/bin/innoextract",
            ),
            patch("exwin.backend.generic_installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 1
            assert detect_installer_type(exe) == "generic"

    def test_generic_when_innoextract_missing(self, tmp_path: Path) -> None:
        exe = tmp_path / "setup.exe"
        exe.touch()
        with patch("exwin.backend.generic_installer.find_innoextract", side_effect=RuntimeError):
            assert detect_installer_type(exe) == "generic"

    def test_msi_detected_by_suffix(self, tmp_path: Path) -> None:
        msi = tmp_path / "installer.msi"
        msi.touch()
        # innoextract should never be probed for an .msi suffix
        with patch("exwin.backend.generic_installer.find_innoextract") as mock_find:
            assert detect_installer_type(msi) == "msi"
            mock_find.assert_not_called()

    def test_msi_detected_case_insensitive(self, tmp_path: Path) -> None:
        msi = tmp_path / "Installer.MSI"
        msi.touch()
        assert detect_installer_type(msi) == "msi"

    def test_archive_detected_by_magic(self, tmp_path: Path) -> None:
        import zipfile

        zpath = tmp_path / "game.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("readme.txt", "hi")
        assert detect_installer_type(zpath) == "archive"


# ---------------------------------------------------------------------------
# run_wine_installer — MSI branch
# ---------------------------------------------------------------------------


class TestRunWineInstallerMsi:
    def test_msi_uses_msiexec_with_wine(self, tmp_path: Path, wine_rt: Runtime) -> None:
        msi = tmp_path / "installer.msi"
        msi.touch()
        prefix = tmp_path / "prefix"
        with patch("exwin.backend.generic_installer.subprocess.Popen") as mock_popen:
            run_wine_installer(msi, prefix, wine_rt)
        cmd = mock_popen.call_args[0][0]
        assert cmd[-3:] == ["msiexec", "/i", str(msi)]

    def test_msi_uses_msiexec_with_proton(self, tmp_path: Path, proton_rt: Runtime) -> None:
        msi = tmp_path / "installer.msi"
        msi.touch()
        prefix = tmp_path / "prefix"
        with patch("exwin.backend.generic_installer.subprocess.Popen") as mock_popen:
            run_wine_installer(msi, prefix, proton_rt)
        cmd = mock_popen.call_args[0][0]
        assert cmd[-3:] == ["msiexec", "/i", str(msi)]
        assert cmd[1] == "run"  # proton run msiexec /i <msi>

    def test_exe_does_not_use_msiexec(self, tmp_path: Path, wine_rt: Runtime) -> None:
        exe = tmp_path / "installer.exe"
        exe.touch()
        prefix = tmp_path / "prefix"
        with patch("exwin.backend.generic_installer.subprocess.Popen") as mock_popen:
            run_wine_installer(exe, prefix, wine_rt)
        cmd = mock_popen.call_args[0][0]
        assert "msiexec" not in cmd


# ---------------------------------------------------------------------------
# scan_candidate_exes
# ---------------------------------------------------------------------------


class TestScanCandidateExes:
    def _make_prefix(self, tmp_path: Path, runtime: Runtime) -> Path:
        """Create a fake drive_c structure."""
        p_root = tmp_path / "prefix"
        if runtime.is_proton:
            drive_c = p_root / "pfx" / "drive_c"
        else:
            drive_c = p_root / "drive_c"
        drive_c.mkdir(parents=True)
        return p_root, drive_c

    def test_finds_exe_in_program_files(self, tmp_path: Path, wine_rt: Runtime) -> None:
        p_root, drive_c = self._make_prefix(tmp_path, wine_rt)
        prog = drive_c / "Program Files" / "MyGame"
        prog.mkdir(parents=True)
        (prog / "Game.exe").touch()

        candidates = scan_candidate_exes(p_root, wine_rt)
        assert len(candidates) == 1
        assert candidates[0].name == "Game.exe"

    def test_skips_windows_dir(self, tmp_path: Path, wine_rt: Runtime) -> None:
        p_root, drive_c = self._make_prefix(tmp_path, wine_rt)
        win = drive_c / "windows"
        win.mkdir()
        (win / "explorer.exe").touch()

        candidates = scan_candidate_exes(p_root, wine_rt)
        assert len(candidates) == 0

    def test_skips_uninstall_exe(self, tmp_path: Path, wine_rt: Runtime) -> None:
        p_root, drive_c = self._make_prefix(tmp_path, wine_rt)
        prog = drive_c / "Program Files" / "MyGame"
        prog.mkdir(parents=True)
        (prog / "unins000.exe").touch()
        (prog / "Game.exe").touch()

        candidates = scan_candidate_exes(p_root, wine_rt)
        assert all(c.name != "unins000.exe" for c in candidates)

    def test_skips_steam_subdir(self, tmp_path: Path, wine_rt: Runtime) -> None:
        p_root, drive_c = self._make_prefix(tmp_path, wine_rt)
        steam = drive_c / "Program Files" / "Steam"
        steam.mkdir(parents=True)
        (steam / "Steam.exe").touch()

        candidates = scan_candidate_exes(p_root, wine_rt)
        assert len(candidates) == 0

    def test_proton_prefix_layout(self, tmp_path: Path, proton_rt: Runtime) -> None:
        p_root, drive_c = self._make_prefix(tmp_path, proton_rt)
        prog = drive_c / "Program Files" / "MyGame"
        prog.mkdir(parents=True)
        (prog / "Game.exe").touch()

        candidates = scan_candidate_exes(p_root, proton_rt)
        assert len(candidates) == 1

    def test_returns_empty_when_no_drive_c(self, tmp_path: Path, wine_rt: Runtime) -> None:
        p_root = tmp_path / "empty_prefix"
        p_root.mkdir()
        assert scan_candidate_exes(p_root, wine_rt) == []


# ---------------------------------------------------------------------------
# pick_best_exe
# ---------------------------------------------------------------------------


class TestPickBestExe:
    def test_returns_none_for_empty(self) -> None:
        assert pick_best_exe([]) is None

    def test_returns_single_candidate(self, tmp_path: Path) -> None:
        exe = tmp_path / "Game.exe"
        exe.write_bytes(b"x" * 1000)
        assert pick_best_exe([exe]) == exe

    def test_prefers_non_unlikely_name(self, tmp_path: Path) -> None:
        game = tmp_path / "Game.exe"
        game.write_bytes(b"x" * 1000)
        launcher = tmp_path / "Launcher.exe"
        launcher.write_bytes(b"x" * 2000)

        result = pick_best_exe([game, launcher])
        assert result == game  # "launcher" is in _UNLIKELY_STEMS

    def test_prefers_shallower_path(self, tmp_path: Path) -> None:
        shallow = tmp_path / "Game.exe"
        shallow.write_bytes(b"x" * 1000)
        deep = tmp_path / "sub" / "Game.exe"
        deep.parent.mkdir()
        deep.write_bytes(b"x" * 1000)

        result = pick_best_exe([deep, shallow])
        assert result == shallow


# ---------------------------------------------------------------------------
# _slugify_app_id
# ---------------------------------------------------------------------------


class TestSlugifyAppId:
    def test_basic(self) -> None:
        assert _slugify_app_id("My Great Game") == "manual-my-great-game"

    def test_special_chars(self) -> None:
        assert _slugify_app_id("Game: The Sequel!") == "manual-game-the-sequel"
