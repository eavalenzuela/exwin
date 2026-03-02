"""Tests for exwin.backend.migrate."""

from __future__ import annotations

from pathlib import Path

import pytest

from exwin.backend.config import Config
from exwin.backend.migrate import move_game_data
from exwin.db.schema import init_db
from exwin.models import AppEntry


def _make_app(
    tmp_path: Path,
    *,
    app_id: str = "gog-12345",
    name: str = "Test Game",
) -> AppEntry:
    install_dir = tmp_path / "apps" / app_id
    prefix_dir = tmp_path / "prefixes" / app_id
    install_dir.mkdir(parents=True)
    prefix_dir.mkdir(parents=True)
    # Simulate a game file
    (install_dir / "game.exe").write_bytes(b"\x00" * 16)
    return AppEntry(
        app_id=app_id,
        name=name,
        source="gog",
        install_path=str(install_dir),
        prefix_path=str(prefix_dir),
    )


@pytest.fixture
def migrated_config(tmp_path: Path) -> Config:
    cfg = Config(data_dir=tmp_path / "exwin")
    cfg._ensure_dirs()
    storage = tmp_path / "external"
    storage.mkdir()
    cfg.storage_root = storage
    return cfg


@pytest.fixture
def db(migrated_config: Config) -> Config:
    init_db(migrated_config.data_dir)
    return migrated_config


class TestMoveGameData:
    def test_raises_without_storage_root(self, db: Config, tmp_path: Path) -> None:
        db.storage_root = None
        app = _make_app(tmp_path)
        with pytest.raises(RuntimeError, match="No storage root"):
            move_game_data(app, db)

    def test_moves_install_dir(self, db: Config, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        new_app = move_game_data(app, db)
        expected = db.installs_dir / app.app_id
        assert Path(new_app.install_path) == expected
        assert (expected / "game.exe").exists()

    def test_old_install_dir_gone(self, db: Config, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        old_install = Path(app.install_path)
        move_game_data(app, db)
        assert not old_install.exists()

    def test_moves_prefix_dir(self, db: Config, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        new_app = move_game_data(app, db)
        expected = db.prefixes_dir / app.app_id
        assert Path(new_app.prefix_path) == expected
        assert expected.is_dir()

    def test_old_prefix_dir_gone(self, db: Config, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        old_prefix = Path(app.prefix_path)
        move_game_data(app, db)
        assert not old_prefix.exists()

    def test_db_paths_updated(self, db: Config, tmp_path: Path) -> None:
        from exwin.db.apps import get_app, insert_app

        app = _make_app(tmp_path)
        insert_app(app)
        new_app = move_game_data(app, db)

        stored = get_app(app.app_id)
        assert stored is not None
        assert stored.install_path == new_app.install_path
        assert stored.prefix_path == new_app.prefix_path

    def test_already_at_target_is_noop(self, db: Config) -> None:
        """If install is already at the storage location, no error and paths unchanged."""
        install_dir = db.installs_dir / "gog-99"
        prefix_dir = db.prefixes_dir / "gog-99"
        install_dir.mkdir(parents=True)
        prefix_dir.mkdir(parents=True)
        (install_dir / "game.exe").write_bytes(b"\x00" * 8)

        app = AppEntry(
            app_id="gog-99",
            name="Already There",
            source="gog",
            install_path=str(install_dir),
            prefix_path=str(prefix_dir),
        )
        new_app = move_game_data(app, db)
        assert new_app.install_path == app.install_path
        assert new_app.prefix_path == app.prefix_path
        assert install_dir.exists()

    def test_raises_if_target_install_exists(self, db: Config, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        # Pre-create the target to trigger the conflict error
        (db.installs_dir / app.app_id).mkdir(parents=True)
        with pytest.raises(RuntimeError, match="Target already exists"):
            move_game_data(app, db)

    def test_on_progress_called(self, db: Config, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        messages: list[str] = []
        move_game_data(app, db, on_progress=messages.append)
        assert any("Moving" in m or "moved" in m.lower() for m in messages)

    def test_generic_install_collocated_prefix(self, db: Config, tmp_path: Path) -> None:
        """Generic installs have prefix_path == install_path; both should move together."""
        install_dir = tmp_path / "apps" / "manual-mygame"
        install_dir.mkdir(parents=True)
        (install_dir / "mygame.exe").write_bytes(b"\x00" * 8)

        app = AppEntry(
            app_id="manual-mygame",
            name="My Game",
            source="manual",
            install_path=str(install_dir),
            prefix_path=str(install_dir),  # same dir as install
        )
        new_app = move_game_data(app, db)
        # Both should point to the new install location
        assert new_app.install_path == new_app.prefix_path
        assert Path(new_app.install_path) == db.installs_dir / "manual-mygame"
