"""Tests for exwin.backend.gog_installer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from exwin.backend.gog_installer import (
    InstallerInfo,
    _parse_info_output,
    app_id_from_info,
    find_cover_art,
    find_primary_exe,
    find_sibling_parts,
    guess_exe,
    parse_game_info,
    validate_checksums,
)

# ---------------------------------------------------------------------------
# _parse_info_output
# ---------------------------------------------------------------------------


class TestParseInfoOutput:
    def test_parses_title(self, tmp_path: Path) -> None:
        output = 'Inspecting "Balrum" - setup data version 5.6.2\n'
        info = _parse_info_output(output, tmp_path / "setup.exe")
        assert info.title == "Balrum"

    def test_parses_game_id(self, tmp_path: Path) -> None:
        output = 'Inspecting "Balrum"\nsetup data version 5.6.2\nGOG.com game ID is 1234567890\n'
        info = _parse_info_output(output, tmp_path / "setup.exe")
        assert info.game_id == "1234567890"

    def test_parses_languages(self, tmp_path: Path) -> None:
        output = 'Inspecting "Test"\n - en-US\n - de-DE\n'
        info = _parse_info_output(output, tmp_path / "setup.exe")
        assert info.languages == ["en-US", "de-DE"]

    def test_parses_setup_version(self, tmp_path: Path) -> None:
        output = "setup data version 5.6.2\n"
        info = _parse_info_output(output, tmp_path / "setup.exe")
        assert info.setup_version == "5.6.2"

    def test_fallback_title_from_filename(self, tmp_path: Path) -> None:
        info = _parse_info_output("", tmp_path / "setup_balrum.exe")
        assert info.title == "setup_balrum"

    def test_empty_output(self, tmp_path: Path) -> None:
        info = _parse_info_output("", tmp_path / "installer.exe")
        assert info.game_id == ""
        assert info.languages == []


# ---------------------------------------------------------------------------
# find_primary_exe
# ---------------------------------------------------------------------------


class TestFindPrimaryExe:
    def test_finds_primary_task(self) -> None:
        game_info = {
            "playTasks": [
                {"isPrimary": True, "type": "FileTask", "path": "Game.exe"},
                {"type": "FileTask", "path": "Config.exe"},
            ]
        }
        assert find_primary_exe(game_info) == "Game.exe"

    def test_falls_back_to_first_file_task(self) -> None:
        game_info = {
            "playTasks": [
                {"type": "URLTask", "link": "http://example.com"},
                {"type": "FileTask", "path": "Launcher.exe"},
            ]
        }
        assert find_primary_exe(game_info) == "Launcher.exe"

    def test_returns_none_on_empty_tasks(self) -> None:
        assert find_primary_exe({"playTasks": []}) is None

    def test_returns_none_on_missing_tasks(self) -> None:
        assert find_primary_exe({}) is None

    def test_ignores_non_file_tasks(self) -> None:
        game_info = {
            "playTasks": [
                {"isPrimary": True, "type": "URLTask", "link": "http://..."},
            ]
        }
        assert find_primary_exe(game_info) is None


# ---------------------------------------------------------------------------
# guess_exe
# ---------------------------------------------------------------------------


class TestGuessExe:
    def test_finds_exe_in_root(self, tmp_path: Path) -> None:
        (tmp_path / "Game.exe").touch()
        assert guess_exe(tmp_path) == "Game.exe"

    def test_skips_redist(self, tmp_path: Path) -> None:
        redist = tmp_path / "__redist"
        redist.mkdir()
        (redist / "vcredist_x64.exe").touch()
        (tmp_path / "RealGame.exe").touch()
        assert guess_exe(tmp_path) == "RealGame.exe"

    def test_skips_unwanted_exes(self, tmp_path: Path) -> None:
        game_dir = tmp_path / "gamedir"
        game_dir.mkdir()
        (game_dir / "setup.exe").touch()
        (game_dir / "MyGame.exe").touch()
        assert guess_exe(game_dir) == "MyGame.exe"

    def test_returns_none_when_empty(self, tmp_path: Path) -> None:
        assert guess_exe(tmp_path) is None

    def test_hint_matching(self, tmp_path: Path) -> None:
        (tmp_path / "RealGame.exe").touch()
        (tmp_path / "Other.exe").touch()
        result = guess_exe(tmp_path, hint="RealGame")
        assert result == "RealGame.exe"

    def test_prefers_root_over_subdir(self, tmp_path: Path) -> None:
        (tmp_path / "Root.exe").touch()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "Deep.exe").touch()
        assert guess_exe(tmp_path) == "Root.exe"


# ---------------------------------------------------------------------------
# parse_game_info
# ---------------------------------------------------------------------------


class TestParseGameInfo:
    def test_finds_info_in_root(self, tmp_path: Path) -> None:
        info = {"gameId": "123", "name": "TestGame"}
        (tmp_path / "goggame-123.info").write_text(json.dumps(info))
        assert parse_game_info(tmp_path) == info

    def test_finds_info_in_app_subdir(self, tmp_path: Path) -> None:
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        info = {"gameId": "456"}
        (app_dir / "goggame-456.info").write_text(json.dumps(info))
        assert parse_game_info(tmp_path) == info

    def test_finds_info_in_game_subdir(self, tmp_path: Path) -> None:
        game_dir = tmp_path / "game"
        game_dir.mkdir()
        info = {"gameId": "789"}
        (game_dir / "goggame-789.info").write_text(json.dumps(info))
        assert parse_game_info(tmp_path) == info

    def test_returns_empty_dict_when_none(self, tmp_path: Path) -> None:
        assert parse_game_info(tmp_path) == {}

    def test_skips_invalid_json(self, tmp_path: Path) -> None:
        (tmp_path / "goggame-bad.info").write_text("not json {{{")
        assert parse_game_info(tmp_path) == {}


# ---------------------------------------------------------------------------
# find_sibling_parts
# ---------------------------------------------------------------------------


class TestFindSiblingParts:
    def test_finds_bin_parts(self, tmp_path: Path) -> None:
        exe = tmp_path / "setup_game.exe"
        exe.touch()
        (tmp_path / "setup_game-1.bin").touch()
        (tmp_path / "setup_game-2.bin").touch()
        parts = find_sibling_parts(exe)
        assert len(parts) == 2

    def test_returns_empty_for_single_installer(self, tmp_path: Path) -> None:
        exe = tmp_path / "setup.exe"
        exe.touch()
        assert find_sibling_parts(exe) == []

    def test_does_not_match_other_stems(self, tmp_path: Path) -> None:
        exe = tmp_path / "setup_game.exe"
        exe.touch()
        (tmp_path / "other_game-1.bin").touch()
        assert find_sibling_parts(exe) == []


# ---------------------------------------------------------------------------
# validate_checksums
# ---------------------------------------------------------------------------


class TestValidateChecksums:
    def test_noop_when_no_hashdb(self, tmp_path: Path) -> None:
        installer = tmp_path / "setup.exe"
        installer.write_bytes(b"data")
        # Should not raise
        validate_checksums(installer)

    def test_validates_matching_checksums(self, tmp_path: Path) -> None:
        import hashlib

        installer = tmp_path / "setup.exe"
        data = b"installer data"
        installer.write_bytes(data)
        md5 = hashlib.md5(data).hexdigest()

        hashdb = tmp_path / "setup.hashdb"
        hashdb.write_text(f"{md5} setup.exe\n")

        # Should not raise
        validate_checksums(installer)

    def test_raises_on_mismatch(self, tmp_path: Path) -> None:
        installer = tmp_path / "setup.exe"
        installer.write_bytes(b"installer data")

        hashdb = tmp_path / "setup.hashdb"
        hashdb.write_text("0000000000000000000000000000dead setup.exe\n")

        with pytest.raises(RuntimeError, match="Checksum mismatch"):
            validate_checksums(installer)

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        installer = tmp_path / "setup.exe"
        installer.write_bytes(b"data")

        hashdb = tmp_path / "setup.hashdb"
        hashdb.write_text("abcdef1234567890 missing_file.bin\n")

        with pytest.raises(RuntimeError, match="Missing installer file"):
            validate_checksums(installer)


# ---------------------------------------------------------------------------
# app_id_from_info
# ---------------------------------------------------------------------------


class TestAppIdFromInfo:
    def test_with_game_id(self) -> None:
        info = InstallerInfo(title="Balrum", game_id="1234567", setup_version="5.6")
        assert app_id_from_info(info) == "gog-1234567"

    def test_fallback_slugify(self) -> None:
        info = InstallerInfo(title="My Great Game!", game_id="", setup_version="5.6")
        assert app_id_from_info(info) == "gog-my-great-game"


# ---------------------------------------------------------------------------
# find_cover_art
# ---------------------------------------------------------------------------


class TestFindCoverArt:
    def test_finds_english_cover(self, tmp_path: Path) -> None:
        tmp_dir = tmp_path / "tmp"
        tmp_dir.mkdir()
        cover = tmp_dir / "12345_english.jpg"
        cover.write_bytes(b"\xff\xd8" * 100)  # ~200 bytes
        result = find_cover_art(tmp_path)
        assert result == cover

    def test_returns_none_when_no_tmp(self, tmp_path: Path) -> None:
        assert find_cover_art(tmp_path) is None

    def test_prefers_smallest_english_jpg(self, tmp_path: Path) -> None:
        tmp_dir = tmp_path / "tmp"
        tmp_dir.mkdir()
        small = tmp_dir / "small_english.jpg"
        small.write_bytes(b"\xff" * 50)
        big = tmp_dir / "big_english.jpg"
        big.write_bytes(b"\xff" * 500)
        result = find_cover_art(tmp_path)
        assert result == small
