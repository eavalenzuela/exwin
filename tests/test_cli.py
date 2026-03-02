"""Tests for M12 — CLI interface (exwin subcommands)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from exwin.backend.config import Config
from exwin.db.apps import get_app, insert_app
from exwin.models import AppEntry


def _run(args: list[str], data_dir: Path) -> subprocess.CompletedProcess:
    """Run `python -m exwin <args>` with EXWIN_DATA_DIR set to data_dir."""
    import os

    env = {**os.environ, "EXWIN_DATA_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, "-m", "exwin", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _app(
    app_id: str = "cli-game",
    install_path: str = "",
    prefix_path: str = "",
) -> AppEntry:
    return AppEntry(
        app_id=app_id,
        name="CLI Game",
        source="gog",
        install_path=install_path,
        prefix_path=prefix_path,
    )


class TestListCommand:
    def test_list_exits_zero(self, db: Config) -> None:
        result = _run(["list"], db.data_dir)
        assert result.returncode == 0

    def test_list_shows_app_name(self, db: Config) -> None:
        insert_app(_app())
        result = _run(["list"], db.data_dir)
        assert result.returncode == 0
        assert "CLI Game" in result.stdout

    def test_list_empty_message(self, db: Config) -> None:
        result = _run(["list"], db.data_dir)
        assert "No games" in result.stdout


class TestRemoveCommand:
    def test_remove_keep_files(self, db: Config, tmp_path: Path) -> None:
        install_dir = tmp_path / "game"
        install_dir.mkdir()
        (install_dir / "game.exe").write_text("exe")
        app = _app(install_path=str(install_dir), prefix_path=str(install_dir))
        insert_app(app)

        result = _run(["remove", app.app_id], db.data_dir)
        assert result.returncode == 0
        assert get_app(app.app_id) is None
        assert install_dir.exists(), "files should be kept when --delete-files not passed"

    def test_remove_delete_files(self, db: Config, tmp_path: Path) -> None:
        install_dir = tmp_path / "game"
        install_dir.mkdir()
        (install_dir / "game.exe").write_text("exe")
        app = _app(install_path=str(install_dir), prefix_path=str(install_dir))
        insert_app(app)

        result = _run(["remove", app.app_id, "--delete-files"], db.data_dir)
        assert result.returncode == 0
        assert not install_dir.exists()
        assert get_app(app.app_id) is None

    def test_unknown_app_remove_exits_nonzero(self, db: Config) -> None:
        result = _run(["remove", "nonexistent-game"], db.data_dir)
        assert result.returncode != 0


class TestMigrateCommand:
    def test_migrate_subcommand(self, tmp_path: Path) -> None:
        from exwin.db.schema import init_db

        data_dir = tmp_path / "exwin"
        storage = tmp_path / "external"
        storage.mkdir()

        cfg = Config(data_dir=data_dir, storage_root=storage)
        cfg._ensure_dirs()
        cfg.save()
        init_db(data_dir)

        install_dir = tmp_path / "old_install"
        install_dir.mkdir()
        (install_dir / "game.exe").write_bytes(b"\x00" * 8)

        app = AppEntry(
            app_id="gog-migrate",
            name="Migrate Game",
            source="gog",
            install_path=str(install_dir),
            prefix_path=str(install_dir),
        )
        insert_app(app)

        result = _run(["migrate", app.app_id], data_dir)
        assert result.returncode == 0

        stored = get_app(app.app_id)
        assert stored is not None
        new_install = Path(stored.install_path)
        assert new_install != install_dir
        assert new_install.is_dir()


class TestBackupSavesCommand:
    def test_backup_saves_subcommand(self, db: Config, tmp_path: Path) -> None:
        from exwin.backend.app_config import AppConfig, save_app_config

        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        (save_dir / "slot1.sav").write_text("data")

        app = _app()
        insert_app(app)

        app_cfg = AppConfig(save_path=str(save_dir))
        save_app_config(app.app_id, db, app_cfg)

        result = _run(["backup-saves", app.app_id], db.data_dir)
        assert result.returncode == 0

        backups_dir = db.data_dir / "saves" / app.app_id
        zips = list(backups_dir.glob("*.zip"))
        assert len(zips) == 1

    def test_backup_saves_no_save_path_exits_nonzero(self, db: Config) -> None:
        insert_app(_app())
        result = _run(["backup-saves", "cli-game"], db.data_dir)
        assert result.returncode != 0

    def test_backup_saves_unknown_app_exits_nonzero(self, db: Config) -> None:
        result = _run(["backup-saves", "no-such-game"], db.data_dir)
        assert result.returncode != 0


class TestRestoreSavesCommand:
    def test_restore_saves_subcommand(self, db: Config, tmp_path: Path) -> None:
        from exwin.backend.app_config import AppConfig, save_app_config
        from exwin.backend.saves import backup_saves

        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        (save_dir / "slot1.sav").write_text("original")

        app = _app()
        insert_app(app)

        app_cfg = AppConfig(save_path=str(save_dir))
        save_app_config(app.app_id, db, app_cfg)

        # Create a backup via the library
        backup_saves(app, app_cfg, db)

        # Corrupt the save
        (save_dir / "slot1.sav").write_text("corrupted")

        result = _run(["restore-saves", app.app_id], db.data_dir)
        assert result.returncode == 0

        content = (save_dir / "slot1.sav").read_text()
        assert content == "original"
