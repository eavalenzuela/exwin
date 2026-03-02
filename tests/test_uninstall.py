"""Tests for the uninstall flow (delete_files flag)."""

from __future__ import annotations

from pathlib import Path

from exwin.backend.config import Config
from exwin.db.apps import get_app, insert_app
from exwin.models import AppEntry


def _make_app(
    tmp_path: Path,
    app_id: str = "test-game",
    *,
    separate_prefix: bool = False,
) -> AppEntry:
    install_dir = tmp_path / "install" / app_id
    install_dir.mkdir(parents=True)
    (install_dir / "game.exe").write_text("fake exe")

    if separate_prefix:
        prefix_dir = tmp_path / "prefix" / app_id
        prefix_dir.mkdir(parents=True)
        (prefix_dir / "prefix.dat").write_text("prefix")
    else:
        prefix_dir = install_dir

    return AppEntry(
        app_id=app_id,
        name="Test Game",
        source="gog",
        install_path=str(install_dir),
        prefix_path=str(prefix_dir),
    )


def _do_uninstall(app: AppEntry, delete_files: bool) -> None:
    """Mirror the window._uninstall_app logic without GTK."""
    import shutil

    from exwin.db.apps import delete_app

    if delete_files:
        install = Path(app.install_path) if app.install_path else None
        prefix = Path(app.prefix_path) if app.prefix_path else None
        if install and install.exists():
            shutil.rmtree(install, ignore_errors=True)
        if prefix and prefix != install and prefix.exists():
            shutil.rmtree(prefix, ignore_errors=True)
    delete_app(app.app_id)


class TestUninstall:
    def test_keep_files_leaves_install_dir(self, db: Config, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        insert_app(app)
        install_dir = Path(app.install_path)

        _do_uninstall(app, delete_files=False)

        assert install_dir.exists(), "install dir should NOT be deleted when keep_files"
        assert get_app(app.app_id) is None, "DB row should be gone"

    def test_delete_files_removes_install_dir(self, db: Config, tmp_path: Path) -> None:
        app = _make_app(tmp_path)
        insert_app(app)
        install_dir = Path(app.install_path)

        _do_uninstall(app, delete_files=True)

        assert not install_dir.exists(), "install dir should be deleted"
        assert get_app(app.app_id) is None

    def test_delete_files_removes_separate_prefix(self, db: Config, tmp_path: Path) -> None:
        app = _make_app(tmp_path, separate_prefix=True)
        insert_app(app)
        install_dir = Path(app.install_path)
        prefix_dir = Path(app.prefix_path)

        _do_uninstall(app, delete_files=True)

        assert not install_dir.exists()
        assert not prefix_dir.exists()

    def test_delete_collocated_prefix_not_double_deleted(self, db: Config, tmp_path: Path) -> None:
        """Generic install: install_path == prefix_path — should not error."""
        app = _make_app(tmp_path, separate_prefix=False)
        insert_app(app)
        install_dir = Path(app.install_path)

        # Should complete without raising even though install == prefix
        _do_uninstall(app, delete_files=True)

        assert not install_dir.exists()
        assert get_app(app.app_id) is None
