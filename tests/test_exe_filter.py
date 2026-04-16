"""Tests for exwin.backend.exe_filter."""

from __future__ import annotations

from pathlib import Path

from exwin.backend.exe_filter import pick_best_exe, scan_dir_for_exes, should_skip


class TestShouldSkip:
    def test_uninstall_exe(self) -> None:
        assert should_skip(Path("game/unins000.exe")) is True

    def test_redist_dir(self) -> None:
        assert should_skip(Path("game/__redist/vcredist.exe")) is True

    def test_normal_exe(self) -> None:
        assert should_skip(Path("game/Game.exe")) is False


class TestScanDirForExes:
    def test_finds_nested(self, tmp_path: Path) -> None:
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "Game.exe").touch()
        (tmp_path / "Launcher.exe").touch()
        results = scan_dir_for_exes(tmp_path)
        assert len(results) == 2

    def test_skips_redist(self, tmp_path: Path) -> None:
        (tmp_path / "__redist").mkdir()
        (tmp_path / "__redist" / "vcredist.exe").touch()
        (tmp_path / "Game.exe").touch()
        results = scan_dir_for_exes(tmp_path)
        assert len(results) == 1
        assert results[0].name == "Game.exe"

    def test_empty_missing_dir(self, tmp_path: Path) -> None:
        assert scan_dir_for_exes(tmp_path / "nope") == []

    def test_shallow_first_ordering(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "Deep.exe"
        deep.parent.mkdir(parents=True)
        deep.touch()
        (tmp_path / "Shallow.exe").touch()
        results = scan_dir_for_exes(tmp_path)
        assert results[0].name == "Shallow.exe"


class TestPickBestExe:
    def test_empty(self) -> None:
        assert pick_best_exe([]) is None

    def test_single(self, tmp_path: Path) -> None:
        exe = tmp_path / "Game.exe"
        exe.write_bytes(b"x" * 100)
        assert pick_best_exe([exe]) == exe

    def test_prefers_game_over_launcher(self, tmp_path: Path) -> None:
        game = tmp_path / "Game.exe"
        launcher = tmp_path / "Launcher.exe"
        game.write_bytes(b"x" * 100)
        launcher.write_bytes(b"x" * 1000)
        assert pick_best_exe([launcher, game]) == game
