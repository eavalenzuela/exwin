"""Tests for exwin.backend.desktop_shortcut."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from exwin.backend.desktop_shortcut import create_shortcut
from exwin.models import AppEntry


def _make_app(app_id: str = "gog-12345", name: str = "Test Game", cover: str = "") -> AppEntry:
    return AppEntry(app_id=app_id, name=name, source="gog", cover_art_path=cover)


@pytest.fixture
def shortcut_dir(tmp_path: Path, monkeypatch):
    """Redirect _APPLICATIONS_DIR to a tmp dir and disable update-desktop-database."""
    apps_dir = tmp_path / "applications"
    monkeypatch.setattr("exwin.backend.desktop_shortcut._APPLICATIONS_DIR", apps_dir)
    # Ensure update-desktop-database is not found so subprocess.run is skipped
    with patch("shutil.which", return_value=None):
        yield apps_dir


class TestCreateShortcut:
    def test_creates_desktop_file(self, shortcut_dir: Path) -> None:
        app = _make_app()
        dest = create_shortcut(app)
        assert dest.exists()

    def test_exec_contains_app_id(self, shortcut_dir: Path) -> None:
        app = _make_app(app_id="gog-99")
        dest = create_shortcut(app)
        content = dest.read_text()
        assert "--launch gog-99" in content

    def test_exec_uses_sys_executable(self, shortcut_dir: Path) -> None:
        app = _make_app()
        dest = create_shortcut(app)
        content = dest.read_text()
        exec_line = next(l for l in content.splitlines() if l.startswith("Exec="))
        assert exec_line.startswith(f"Exec={sys.executable}")

    def test_icon_uses_cover_art_when_present(self, shortcut_dir: Path, tmp_path: Path) -> None:
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"")
        app = _make_app(cover=str(cover))
        dest = create_shortcut(app)
        content = dest.read_text()
        icon_line = next(l for l in content.splitlines() if l.startswith("Icon="))
        assert icon_line == f"Icon={cover}"

    def test_icon_fallback_when_no_cover(self, shortcut_dir: Path) -> None:
        app = _make_app(cover="")
        dest = create_shortcut(app)
        content = dest.read_text()
        icon_line = next(l for l in content.splitlines() if l.startswith("Icon="))
        assert icon_line == "Icon=applications-games-symbolic"

    def test_icon_fallback_when_cover_missing_on_disk(self, shortcut_dir: Path) -> None:
        app = _make_app(cover="/nonexistent/path/cover.jpg")
        dest = create_shortcut(app)
        content = dest.read_text()
        icon_line = next(l for l in content.splitlines() if l.startswith("Icon="))
        assert icon_line == "Icon=applications-games-symbolic"

    def test_name_field(self, shortcut_dir: Path) -> None:
        app = _make_app(name="My Awesome Game")
        dest = create_shortcut(app)
        content = dest.read_text()
        assert "Name=My Awesome Game" in content

    def test_categories_field(self, shortcut_dir: Path) -> None:
        app = _make_app()
        dest = create_shortcut(app)
        assert "Categories=Game;" in dest.read_text()

    def test_overwrite_existing(self, shortcut_dir: Path) -> None:
        app = _make_app(name="First Name")
        create_shortcut(app)
        app2 = _make_app(name="Second Name")
        dest = create_shortcut(app2)
        assert "Name=Second Name" in dest.read_text()
        assert "Name=First Name" not in dest.read_text()
