"""Tests for M7 — playtime tracking."""

from __future__ import annotations

from exwin.backend.config import Config
from exwin.db.apps import get_app, insert_app, update_playtime
from exwin.models import AppEntry, AppSource
from exwin.util import fmt_playtime as _fmt_playtime


def _app(app_id: str = "pt-game") -> AppEntry:
    return AppEntry(app_id=app_id, name="PT Game", source=AppSource.GOG)


class TestUpdatePlaytime:
    def test_update_playtime_accumulates(self, db: Config) -> None:
        insert_app(_app())
        update_playtime("pt-game", 120)
        update_playtime("pt-game", 80)
        app = get_app("pt-game")
        assert app is not None
        assert app.playtime_seconds == 200

    def test_update_playtime_zero_noop(self, db: Config) -> None:
        insert_app(_app())
        update_playtime("pt-game", 0)
        app = get_app("pt-game")
        assert app is not None
        assert app.playtime_seconds == 0


class TestFmtPlaytime:
    def test_lt_60s(self) -> None:
        assert _fmt_playtime(0) == "< 1m"
        assert _fmt_playtime(59) == "< 1m"

    def test_minutes_only(self) -> None:
        assert _fmt_playtime(90) == "1m"
        assert _fmt_playtime(3599) == "59m"

    def test_hours_and_minutes(self) -> None:
        assert _fmt_playtime(7500) == "2h 5m"
        assert _fmt_playtime(3600) == "1h 0m"

    def test_exactly_one_hour(self) -> None:
        assert _fmt_playtime(3600) == "1h 0m"


class TestAppEntryPlaytime:
    def test_defaults_to_zero(self, db: Config) -> None:
        insert_app(_app())
        app = get_app("pt-game")
        assert app is not None
        assert app.playtime_seconds == 0
