"""Tests for exwin.db.schema and exwin.db.apps."""

from __future__ import annotations

from pathlib import Path

from exwin.backend.config import Config
from exwin.db.apps import (
    delete_app,
    get_all_apps,
    get_app,
    insert_app,
    update_cover_art,
    update_description,
    update_last_launched,
)
from exwin.models import AppEntry, AppSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _app(
    app_id: str = "test-app", name: str = "Test App", source: AppSource = AppSource.GOG
) -> AppEntry:
    return AppEntry(app_id=app_id, name=name, source=source)


# ---------------------------------------------------------------------------
# insert / get
# ---------------------------------------------------------------------------


class TestInsertAndGet:
    def test_get_returns_none_when_missing(self, db: Config) -> None:
        assert get_app("nonexistent") is None

    def test_insert_and_retrieve(self, db: Config) -> None:
        insert_app(_app())
        app = get_app("test-app")
        assert app is not None
        assert app.app_id == "test-app"
        assert app.name == "Test App"
        assert app.source == AppSource.GOG

    def test_optional_fields_default_empty(self, db: Config) -> None:
        insert_app(_app())
        app = get_app("test-app")
        assert app is not None
        assert app.install_path is None
        assert app.exe_path == ""
        assert app.cover_art_path is None
        assert app.description == ""

    def test_insert_preserves_install_path(self, db: Config) -> None:
        entry = _app()
        entry.install_path = Path("/games/myapp")
        insert_app(entry)
        assert get_app("test-app").install_path == Path("/games/myapp")

    def test_insert_preserves_exe_path(self, db: Config) -> None:
        entry = _app()
        entry.exe_path = "game/myapp.exe"
        insert_app(entry)
        assert get_app("test-app").exe_path == "game/myapp.exe"


# ---------------------------------------------------------------------------
# get_all_apps
# ---------------------------------------------------------------------------


class TestGetAllApps:
    def test_empty_library(self, db: Config) -> None:
        assert get_all_apps() == []

    def test_returns_all_entries(self, db: Config) -> None:
        insert_app(_app("app-a", "Alpha"))
        insert_app(_app("app-b", "Beta"))
        ids = {a.app_id for a in get_all_apps()}
        assert ids == {"app-a", "app-b"}

    def test_sorted_case_insensitive(self, db: Config) -> None:
        insert_app(_app("app-z", "Zebra"))
        insert_app(_app("app-a", "apple"))
        insert_app(_app("app-m", "Mango"))
        names = [a.name for a in get_all_apps()]
        assert names == sorted(names, key=str.lower)


# ---------------------------------------------------------------------------
# delete_app
# ---------------------------------------------------------------------------


class TestDeleteApp:
    def test_delete_removes_entry(self, db: Config) -> None:
        insert_app(_app())
        delete_app("test-app")
        assert get_app("test-app") is None

    def test_delete_nonexistent_is_noop(self, db: Config) -> None:
        delete_app("nonexistent")  # must not raise


# ---------------------------------------------------------------------------
# update helpers
# ---------------------------------------------------------------------------


class TestUpdateCoverArt:
    def test_updates_field(self, db: Config) -> None:
        insert_app(_app())
        update_cover_art("test-app", Path("/some/cover.jpg"))
        assert get_app("test-app").cover_art_path == Path("/some/cover.jpg")

    def test_can_overwrite(self, db: Config) -> None:
        insert_app(_app())
        update_cover_art("test-app", Path("/old.jpg"))
        update_cover_art("test-app", Path("/new.jpg"))
        assert get_app("test-app").cover_art_path == Path("/new.jpg")


class TestUpdateLastLaunched:
    def test_updates_timestamp(self, db: Config) -> None:
        insert_app(_app())
        update_last_launched("test-app", "2024-01-01T12:00:00")
        assert get_app("test-app").last_launched == "2024-01-01T12:00:00"


class TestUpdateDescription:
    def test_updates_field(self, db: Config) -> None:
        insert_app(_app())
        update_description("test-app", "A great game.")
        assert get_app("test-app").description == "A great game."
