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
    scan_prefix_extras,
    wait_for_prefix_idle,
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

    def test_cwd_passed_to_popen(self, tmp_path: Path, wine_rt: Runtime) -> None:
        exe = tmp_path / "patch.exe"
        exe.touch()
        prefix = tmp_path / "prefix"
        game_dir = tmp_path / "game"
        with patch("exwin.backend.generic_installer.subprocess.Popen") as mock_popen:
            run_wine_installer(exe, prefix, wine_rt, cwd=game_dir)
        assert mock_popen.call_args[1]["cwd"] == str(game_dir)

    def test_cwd_defaults_to_none(self, tmp_path: Path, wine_rt: Runtime) -> None:
        exe = tmp_path / "installer.exe"
        exe.touch()
        prefix = tmp_path / "prefix"
        with patch("exwin.backend.generic_installer.subprocess.Popen") as mock_popen:
            run_wine_installer(exe, prefix, wine_rt)
        assert mock_popen.call_args[1]["cwd"] is None


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

    def test_skip_token_in_prefix_path_does_not_exclude_game(
        self, tmp_path: Path, proton_rt: Runtime
    ) -> None:
        """A prefix dir named after the installer (…-setup) must not filter every exe.

        SKIP_DIRS tokens ("setup", "unins", …) are matched against the path
        relative to drive_c, not the absolute path — otherwise a prefix like
        `manual-nympho-…-setup` smuggles "setup" into every candidate.
        """
        # p_root's own path contains the skip token "setup".
        p_root = tmp_path / "manual-game-setup"
        drive_c = p_root / "pfx" / "drive_c"
        prog = drive_c / "Program Files (x86)" / "MyGame"
        prog.mkdir(parents=True)
        (prog / "Game.exe").touch()

        candidates = scan_candidate_exes(p_root, proton_rt)
        assert [c.name for c in candidates] == ["Game.exe"]

    def test_skip_token_still_filters_within_install(
        self, tmp_path: Path, proton_rt: Runtime
    ) -> None:
        """SKIP_DIRS still filters a real setup/ subdir under the install."""
        p_root, drive_c = self._make_prefix(tmp_path, proton_rt)
        prog = drive_c / "Program Files (x86)" / "MyGame"
        (prog / "setup").mkdir(parents=True)
        (prog / "setup" / "vcredist.exe").touch()
        (prog / "Game.exe").touch()

        candidates = scan_candidate_exes(p_root, proton_rt)
        assert [c.name for c in candidates] == ["Game.exe"]


# ---------------------------------------------------------------------------
# scan_prefix_extras
# ---------------------------------------------------------------------------


class TestScanPrefixExtras:
    def test_finds_game_extracted_beside_drive_c(self, tmp_path: Path, proton_rt: Runtime) -> None:
        """A RAR SFX that unpacks into the prefix root (not drive_c) is still found."""
        p_root = tmp_path / "manual-game.part1"
        (p_root / "pfx" / "drive_c").mkdir(parents=True)  # empty prefix
        game = p_root / "Game" / "WinRoot" / "engine"
        game.mkdir(parents=True)
        (game / "lcsebody.exe").touch()

        assert scan_candidate_exes(p_root, proton_rt) == []  # drive_c is empty
        extras = scan_prefix_extras(p_root, proton_rt)
        assert [e.name for e in extras] == ["lcsebody.exe"]

    def test_ignores_exes_inside_the_wine_prefix(self, tmp_path: Path, proton_rt: Runtime) -> None:
        """Exes under pfx/ are the drive_c scan's job — don't double-count them."""
        p_root = tmp_path / "prefix"
        dc = p_root / "pfx" / "drive_c" / "windows"
        dc.mkdir(parents=True)
        (dc / "explorer.exe").touch()

        assert scan_prefix_extras(p_root, proton_rt) == []

    def test_filters_installer_and_msi_runtime_exes(
        self, tmp_path: Path, proton_rt: Runtime
    ) -> None:
        """setup.exe / instmsi*.exe are noise, not the game."""
        p_root = tmp_path / "prefix"
        (p_root / "pfx" / "drive_c").mkdir(parents=True)
        pkg = p_root / "Game"
        pkg.mkdir(parents=True)
        for name in ("setup.exe", "instmsia.exe", "instmsiw.exe"):
            (pkg / name).touch()
        (pkg / "WinRoot" / "engine").mkdir(parents=True)
        (pkg / "WinRoot" / "engine" / "lcsebody.exe").touch()

        extras = scan_prefix_extras(p_root, proton_rt)
        assert [e.name for e in extras] == ["lcsebody.exe"]


# ---------------------------------------------------------------------------
# wait_for_prefix_idle
# ---------------------------------------------------------------------------


class TestWaitForPrefixIdle:
    def test_proton_waits_on_pfx_wineserver(self, tmp_path: Path, proton_rt: Runtime) -> None:
        """Proton: invoke <path>/files/bin/wineserver -w with WINEPREFIX=<p_root>/pfx."""
        wineserver = proton_rt.path / "files" / "bin" / "wineserver"
        p_root = tmp_path / "compat"
        with (
            patch("exwin.backend.generic_installer.subprocess.run") as run,
            patch.object(Path, "exists", return_value=True),
        ):
            wait_for_prefix_idle(p_root, proton_rt)
        cmd, kwargs = run.call_args[0][0], run.call_args[1]
        assert cmd == [str(wineserver), "-w"]
        assert kwargs["env"]["WINEPREFIX"] == str(p_root / "pfx")

    def test_wine_waits_on_root_wineserver(self, tmp_path: Path, wine_rt: Runtime) -> None:
        """Plain Wine: wineserver lives at <path>/bin, WINEPREFIX is the root itself."""
        p_root = tmp_path / "prefix"
        with (
            patch("exwin.backend.generic_installer.subprocess.run") as run,
            patch.object(Path, "exists", return_value=True),
        ):
            wait_for_prefix_idle(p_root, wine_rt)
        cmd, kwargs = run.call_args[0][0], run.call_args[1]
        assert cmd == [str(wine_rt.path / "bin" / "wineserver"), "-w"]
        assert kwargs["env"]["WINEPREFIX"] == str(p_root)

    def test_noop_when_wineserver_missing(self, tmp_path: Path, proton_rt: Runtime) -> None:
        """Best-effort: a missing wineserver binary must never block the install."""
        with patch("exwin.backend.generic_installer.subprocess.run") as run:
            wait_for_prefix_idle(tmp_path / "compat", proton_rt)  # binary does not exist
        run.assert_not_called()

    def test_swallows_timeout(self, tmp_path: Path, proton_rt: Runtime) -> None:
        """A hung wait must be swallowed, not propagated to the caller."""
        import subprocess as _sp

        with (
            patch.object(Path, "exists", return_value=True),
            patch(
                "exwin.backend.generic_installer.subprocess.run",
                side_effect=_sp.TimeoutExpired(cmd="wineserver", timeout=1),
            ),
        ):
            wait_for_prefix_idle(tmp_path / "compat", proton_rt, timeout=1)  # must not raise


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
