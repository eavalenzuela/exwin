"""Tests for exwin.backend.umu."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from exwin.backend import umu
from exwin.models import AppEntry, AppSource


def _app(**overrides) -> AppEntry:
    defaults: dict = {
        "app_id": "test-app",
        "name": "Test",
        "source": AppSource.MANUAL,
        "install_path": Path("/tmp/game"),
        "prefix_path": Path("/tmp/prefix"),
        "exe_path": "Game.exe",
    }
    defaults.update(overrides)
    return AppEntry(**defaults)


class TestIsAvailable:
    def test_true_when_on_path(self) -> None:
        with patch("exwin.backend.umu.shutil.which", return_value="/usr/bin/umu-run"):
            assert umu.is_available() is True

    def test_false_when_missing(self) -> None:
        with patch("exwin.backend.umu.shutil.which", return_value=None):
            assert umu.is_available() is False


class TestResolveGameId:
    def test_prefers_steam_appid(self) -> None:
        app = _app(steam_appid=220)
        assert umu.resolve_gameid(app) == "220"

    def test_falls_back_to_zero_when_missing(self) -> None:
        app = _app(steam_appid=None)
        assert umu.resolve_gameid(app) == "0"

    def test_falls_back_to_zero_when_zero(self) -> None:
        app = _app(steam_appid=0)
        assert umu.resolve_gameid(app) == "0"
