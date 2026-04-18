"""Tests for exwin.backend.folder_import."""

from __future__ import annotations

from pathlib import Path

import pytest

from exwin.backend.config import Config
from exwin.backend.folder_import import copy_folder_into_installs, scan_folder_for_exes

# ---------------------------------------------------------------------------
# scan_folder_for_exes
# ---------------------------------------------------------------------------


class TestScanFolderForExes:
    def test_empty_folder_returns_empty(self, tmp_path: Path) -> None:
        assert scan_folder_for_exes(tmp_path) == []

    def test_missing_folder_returns_empty(self, tmp_path: Path) -> None:
        assert scan_folder_for_exes(tmp_path / "nope") == []

    def test_single_exe_is_first(self, tmp_path: Path) -> None:
        (tmp_path / "Game.exe").write_bytes(b"x" * 1024)
        assert scan_folder_for_exes(tmp_path) == [tmp_path / "Game.exe"]

    def test_ranks_game_above_launcher(self, tmp_path: Path) -> None:
        """pick_best_exe should demote UNLIKELY_STEMS (launcher/helper/etc.)."""
        (tmp_path / "Launcher.exe").write_bytes(b"x" * 200)
        (tmp_path / "Game.exe").write_bytes(b"x" * 2_000_000)
        result = scan_folder_for_exes(tmp_path)
        assert result[0].name == "Game.exe"
        assert {p.name for p in result} == {"Game.exe", "Launcher.exe"}

    def test_filters_installer_artefacts(self, tmp_path: Path) -> None:
        # Nest in a neutral subdir so pytest's tmp_path (which may include
        # words like "uninstall" in its name) doesn't trip the substring filter.
        root = tmp_path / "game"
        root.mkdir()
        (root / "Game.exe").touch()
        (root / "unins000.exe").touch()
        (root / "setup.exe").touch()
        redist = root / "__redist"
        redist.mkdir()
        (redist / "vcredist_x64.exe").touch()
        result = scan_folder_for_exes(root)
        assert [p.name for p in result] == ["Game.exe"]

    def test_shallow_over_deep(self, tmp_path: Path) -> None:
        """Shallower paths tie-break ahead of deep ones when size/name score equal."""
        (tmp_path / "Game.exe").write_bytes(b"x" * 1000)
        deep = tmp_path / "sub" / "nested"
        deep.mkdir(parents=True)
        (deep / "Tool.exe").write_bytes(b"x" * 1000)
        result = scan_folder_for_exes(tmp_path)
        assert result[0].name == "Game.exe"


# ---------------------------------------------------------------------------
# copy_folder_into_installs
# ---------------------------------------------------------------------------


class TestCopyFolderIntoInstalls:
    def test_copies_contents(self, tmp_config: Config, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "Game.exe").write_text("binary")
        (src / "data").mkdir()
        (src / "data" / "asset.dat").write_text("asset")

        dest = copy_folder_into_installs(src, "my-app", tmp_config)

        assert dest == tmp_config.installs_dir / "my-app"
        assert (dest / "Game.exe").read_text() == "binary"
        assert (dest / "data" / "asset.dat").read_text() == "asset"

    def test_existing_dest_raises(self, tmp_config: Config, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "Game.exe").touch()

        # Pre-create the destination so the copy should refuse to clobber.
        (tmp_config.installs_dir / "my-app").mkdir(parents=True)

        with pytest.raises(FileExistsError):
            copy_folder_into_installs(src, "my-app", tmp_config)

    def test_progress_callback_invoked(self, tmp_config: Config, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "Game.exe").touch()

        messages: list[str] = []
        copy_folder_into_installs(src, "my-app", tmp_config, on_progress=messages.append)

        assert messages, "progress callback should be called at least once"
        assert any("Copying" in m for m in messages)
