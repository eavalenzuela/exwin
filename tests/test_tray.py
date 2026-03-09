"""Tests for exwin.backend.tray — unit tests for TrayIcon (no DBus needed)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from exwin.backend.tray import TrayIcon


class TestTrayIconConstruction:
    def test_initial_state(self) -> None:
        tray = TrayIcon(
            icon_name="test-icon",
            title="Test App",
            on_activate=lambda: None,
            on_quit=lambda: None,
        )
        assert tray.running is False

    def test_stop_noop_when_not_running(self) -> None:
        tray = TrayIcon(
            icon_name="test-icon",
            title="Test",
            on_activate=lambda: None,
            on_quit=lambda: None,
        )
        # Should not raise
        tray.stop()
        assert tray.running is False


class TestTrayIconProperties:
    def test_sni_get_property_id(self) -> None:
        tray = TrayIcon(
            icon_name="my-icon",
            title="My App",
            on_activate=lambda: None,
            on_quit=lambda: None,
        )
        result = tray._sni_get_property(None, None, None, None, "Id")
        assert result is not None
        assert result.unpack() == tray._bus_name

    def test_sni_get_property_category(self) -> None:
        tray = TrayIcon("i", "t", lambda: None, lambda: None)
        result = tray._sni_get_property(None, None, None, None, "Category")
        assert result.unpack() == "ApplicationStatus"

    def test_sni_get_property_title(self) -> None:
        tray = TrayIcon("i", "MyTitle", lambda: None, lambda: None)
        result = tray._sni_get_property(None, None, None, None, "Title")
        assert result.unpack() == "MyTitle"

    def test_sni_get_property_icon(self) -> None:
        tray = TrayIcon("my-icon", "t", lambda: None, lambda: None)
        result = tray._sni_get_property(None, None, None, None, "IconName")
        assert result.unpack() == "my-icon"

    def test_sni_get_property_menu(self) -> None:
        tray = TrayIcon("i", "t", lambda: None, lambda: None)
        result = tray._sni_get_property(None, None, None, None, "Menu")
        assert result.unpack() == "/MenuObject"

    def test_sni_get_property_unknown(self) -> None:
        tray = TrayIcon("i", "t", lambda: None, lambda: None)
        result = tray._sni_get_property(None, None, None, None, "Nonexistent")
        assert result is None


class TestMenuProperties:
    def test_menu_version(self) -> None:
        tray = TrayIcon("i", "t", lambda: None, lambda: None)
        result = tray._menu_get_property(None, None, None, None, "Version")
        assert result.unpack() == 3

    def test_menu_text_direction(self) -> None:
        tray = TrayIcon("i", "t", lambda: None, lambda: None)
        result = tray._menu_get_property(None, None, None, None, "TextDirection")
        assert result.unpack() == "ltr"

    def test_menu_status(self) -> None:
        tray = TrayIcon("i", "t", lambda: None, lambda: None)
        result = tray._menu_get_property(None, None, None, None, "Status")
        assert result.unpack() == "normal"

    def test_menu_unknown(self) -> None:
        tray = TrayIcon("i", "t", lambda: None, lambda: None)
        result = tray._menu_get_property(None, None, None, None, "Unknown")
        assert result is None


class TestLayoutTuple:
    def test_build_layout_includes_show_and_quit(self) -> None:
        tray = TrayIcon("i", "MyApp", lambda: None, lambda: None)
        layout = tray._build_layout_tuple()
        # Root is (0, {}, [children...])
        assert layout[0] == 0
        assert len(layout[2]) == 2  # Show + Quit items


class TestSniMethodCall:
    def test_activate_calls_on_activate(self) -> None:
        activated = []
        tray = TrayIcon("i", "t", on_activate=lambda: activated.append(True), on_quit=lambda: None)
        invocation = MagicMock()
        from gi.repository import GLib

        tray._sni_method_call(
            None, None, None, None, "Activate", GLib.Variant("(ii)", (0, 0)), invocation
        )
        assert activated == [True]
        invocation.return_value.assert_called_once()

    def test_secondary_activate_calls_on_quit(self) -> None:
        quit_calls = []
        tray = TrayIcon("i", "t", on_activate=lambda: None, on_quit=lambda: quit_calls.append(True))
        invocation = MagicMock()
        from gi.repository import GLib

        tray._sni_method_call(
            None, None, None, None, "SecondaryActivate", GLib.Variant("(ii)", (0, 0)), invocation
        )
        assert quit_calls == [True]


class TestStartStop:
    def test_start_returns_false_on_dbus_error(self) -> None:
        from gi.repository import GLib

        tray = TrayIcon("i", "t", lambda: None, lambda: None)
        with patch("exwin.backend.tray.Gio.bus_get_sync", side_effect=GLib.Error):
            result = tray.start()
        assert result is False
        assert tray.running is False
