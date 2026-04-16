"""Tests for exwin.backend.archive_installer."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from exwin.backend.archive_installer import (
    _7Z_MAGIC,
    _RAR_MAGIC,
    count_archive_members,
    detect_archive_type,
    extract_archive,
    flatten_single_toplevel,
    slugify_app_id,
)

# ---------------------------------------------------------------------------
# detect_archive_type
# ---------------------------------------------------------------------------


class TestDetectArchiveType:
    def test_zip(self, tmp_path: Path) -> None:
        path = tmp_path / "x.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("hello.txt", "hi")
        assert detect_archive_type(path) == "zip"

    def test_7z_magic(self, tmp_path: Path) -> None:
        path = tmp_path / "x.7z"
        path.write_bytes(_7Z_MAGIC + b"\x00" * 10)
        assert detect_archive_type(path) == "7z"

    def test_rar_magic(self, tmp_path: Path) -> None:
        path = tmp_path / "x.rar"
        path.write_bytes(_RAR_MAGIC + b"\x00" * 10)
        assert detect_archive_type(path) == "rar"

    def test_not_an_archive(self, tmp_path: Path) -> None:
        path = tmp_path / "x.exe"
        path.write_bytes(b"MZ" + b"\x00" * 10)
        assert detect_archive_type(path) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        assert detect_archive_type(tmp_path / "nope.zip") is None


# ---------------------------------------------------------------------------
# extract_archive — zip only (stdlib, no external tool dependency)
# ---------------------------------------------------------------------------


class TestExtractZip:
    def test_extracts_all_files(self, tmp_path: Path) -> None:
        src = tmp_path / "game.zip"
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("readme.txt", "hi")
            zf.writestr("bin/game.exe", b"MZ\x00\x00")
        dest = tmp_path / "out"
        extract_archive(src, dest)
        assert (dest / "readme.txt").read_text() == "hi"
        assert (dest / "bin" / "game.exe").exists()

    def test_progress_callbacks_fire(self, tmp_path: Path) -> None:
        src = tmp_path / "game.zip"
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("a.txt", "a")
            zf.writestr("b.txt", "b")
            zf.writestr("c.txt", "c")
        dest = tmp_path / "out"

        progress_calls: list[tuple[int, int]] = []
        log_calls: list[str] = []
        extract_archive(
            src,
            dest,
            on_progress=log_calls.append,
            on_file_progress=lambda c, t: progress_calls.append((c, t)),
        )
        assert progress_calls == [(1, 3), (2, 3), (3, 3)]
        assert any("Extracting" in m for m in log_calls)

    def test_unknown_format_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "garbage.bin"
        bad.write_bytes(b"not an archive")
        with pytest.raises(RuntimeError, match="Unknown archive format"):
            extract_archive(bad, tmp_path / "out")


# ---------------------------------------------------------------------------
# count_archive_members
# ---------------------------------------------------------------------------


class TestCountArchiveMembers:
    def test_zip_count(self, tmp_path: Path) -> None:
        path = tmp_path / "x.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("a.txt", "a")
            zf.writestr("b.txt", "b")
            zf.writestr("subdir/c.txt", "c")
        assert count_archive_members(path) == 3

    def test_unknown_returns_zero(self, tmp_path: Path) -> None:
        bad = tmp_path / "garbage.bin"
        bad.write_bytes(b"nope")
        assert count_archive_members(bad) == 0

    def test_7z_parses_path_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "x.7z"
        path.write_bytes(_7Z_MAGIC + b"\x00" * 10)
        stdout = "Path = a.txt\nSize = 1\n\nPath = b.txt\nSize = 1\n"
        with (
            patch("exwin.backend.archive_installer._find_7z", return_value="/usr/bin/7z"),
            patch("exwin.backend.archive_installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = stdout
            assert count_archive_members(path) == 2


# ---------------------------------------------------------------------------
# flatten_single_toplevel
# ---------------------------------------------------------------------------


class TestFlattenSingleToplevel:
    def test_flattens_single_nested_folder(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        nested = root / "MyGame"
        nested.mkdir(parents=True)
        (nested / "game.exe").write_text("x")
        (nested / "data.pak").write_text("y")

        flatten_single_toplevel(root)

        assert (root / "game.exe").exists()
        assert (root / "data.pak").exists()
        assert not (root / "MyGame").exists()

    def test_leaves_multiple_entries_alone(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        (root / "a.exe").write_text("a")
        (root / "b.pak").write_text("b")

        flatten_single_toplevel(root)

        assert (root / "a.exe").exists()
        assert (root / "b.pak").exists()

    def test_leaves_single_file_alone(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        (root / "game.exe").write_text("x")

        flatten_single_toplevel(root)

        assert (root / "game.exe").exists()


# ---------------------------------------------------------------------------
# slugify_app_id
# ---------------------------------------------------------------------------


class TestSlugifyAppId:
    def test_basic(self) -> None:
        assert slugify_app_id("My Great Game") == "archive-my-great-game"

    def test_special_chars(self) -> None:
        assert slugify_app_id("Game: The Sequel!") == "archive-game-the-sequel"

    def test_empty(self) -> None:
        assert slugify_app_id("") == "archive-unnamed"
