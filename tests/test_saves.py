"""Tests for M8 — save file backup/restore."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from exwin.backend.app_config import AppConfig
from exwin.backend.config import Config
from exwin.backend.saves import backup_saves, list_backups, restore_saves
from exwin.models import AppEntry, AppSource


def _app(app_id: str = "save-game") -> AppEntry:
    return AppEntry(app_id=app_id, name="Save Game", source=AppSource.GOG)


def _cfg(save_path: str) -> AppConfig:
    return AppConfig(save_path=save_path)


class TestBackupSaves:
    def test_backup_creates_zip(self, tmp_config: Config, tmp_path: Path) -> None:
        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        (save_dir / "slot1.sav").write_text("save data")

        app = _app()
        cfg = _cfg(str(save_dir))
        dest = backup_saves(app, cfg, tmp_config)

        assert dest.exists()
        assert dest.suffix == ".zip"

    def test_backup_zip_contains_files(self, tmp_config: Config, tmp_path: Path) -> None:
        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        (save_dir / "slot1.sav").write_text("save data")
        (save_dir / "slot2.sav").write_text("more data")

        app = _app()
        cfg = _cfg(str(save_dir))
        dest = backup_saves(app, cfg, tmp_config)

        with zipfile.ZipFile(dest) as zf:
            names = zf.namelist()
        assert any("slot1.sav" in n for n in names)
        assert any("slot2.sav" in n for n in names)

    def test_backup_raises_when_save_path_missing(self, tmp_config: Config, tmp_path: Path) -> None:
        app = _app()
        cfg = _cfg(str(tmp_path / "nonexistent"))

        with pytest.raises(FileNotFoundError):
            backup_saves(app, cfg, tmp_config)

    def test_backup_single_file(self, tmp_config: Config, tmp_path: Path) -> None:
        save_file = tmp_path / "save.dat"
        save_file.write_text("data")

        app = _app()
        cfg = _cfg(str(save_file))
        dest = backup_saves(app, cfg, tmp_config)

        with zipfile.ZipFile(dest) as zf:
            assert "save.dat" in zf.namelist()


class TestListBackups:
    def test_list_backups_newest_first(self, tmp_config: Config, tmp_path: Path) -> None:
        import time

        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        (save_dir / "s.sav").write_text("x")

        app = _app()
        cfg = _cfg(str(save_dir))

        backup_saves(app, cfg, tmp_config)
        time.sleep(0.01)  # ensure different timestamp (microsecond-precision filename)
        backup_saves(app, cfg, tmp_config)

        backups = list_backups(app.app_id, tmp_config)
        assert len(backups) == 2
        # Newest first: dest2 should come before dest1
        assert backups[0].name >= backups[1].name

    def test_list_backups_empty_when_none(self, tmp_config: Config) -> None:
        backups = list_backups("no-such-game", tmp_config)
        assert backups == []


class TestRestoreSaves:
    def test_restore_extracts_zip(self, tmp_config: Config, tmp_path: Path) -> None:
        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        (save_dir / "slot1.sav").write_text("original")

        app = _app()
        cfg = _cfg(str(save_dir))
        dest = backup_saves(app, cfg, tmp_config)

        # Overwrite save
        (save_dir / "slot1.sav").write_text("corrupted")

        restore_saves(dest, cfg)

        content = (save_dir / "slot1.sav").read_text()
        assert content == "original"
