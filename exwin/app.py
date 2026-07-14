"""Top-level Adw.Application."""

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib  # noqa: E402

from exwin.backend.config import Config  # noqa: E402
from exwin.backend.launcher import Launcher  # noqa: E402
from exwin.backend.runtime import scan_runtimes  # noqa: E402
from exwin.backend.tray import TrayIcon  # noqa: E402
from exwin.db.runtimes import sync_runtimes  # noqa: E402
from exwin.db.schema import init_db  # noqa: E402
from exwin.window import ExwinWindow  # noqa: E402

APP_ID = "io.github.exwin"

_SCHEME_MAP = {
    "system": Adw.ColorScheme.DEFAULT,
    "light": Adw.ColorScheme.FORCE_LIGHT,
    "dark": Adw.ColorScheme.FORCE_DARK,
}


def _apply_color_scheme(name: str) -> None:
    Adw.StyleManager.get_default().set_color_scheme(_SCHEME_MAP.get(name, Adw.ColorScheme.DEFAULT))


class ExwinApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.config = Config.load()
        init_db(self.config.data_dir)
        _apply_color_scheme(self.config.color_scheme)

        # Scan for runtimes and persist them to the DB on every startup.
        # The result (with db_ids populated) is kept for the window to use.
        self.runtimes = sync_runtimes(scan_runtimes())
        self.launcher = Launcher(self.config)
        self._tray: TrayIcon | None = None

        # Keyboard shortcuts
        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("app.search", ["<Control>f"])

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)

        search_action = Gio.SimpleAction.new("search", None)
        search_action.connect("activate", self._on_search_accel)
        self.add_action(search_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

    def _on_search_accel(self, _action: Gio.SimpleAction, _param) -> None:  # noqa: ANN001
        win = self.props.active_window
        if win and hasattr(win, "toggle_search"):
            win.toggle_search()

    def _on_about(self, _action: Gio.SimpleAction, _param) -> None:  # noqa: ANN001
        from gi.repository import Gtk

        from exwin import __version__

        dialog = Adw.AboutDialog(
            application_name="exwin",
            application_icon=APP_ID,
            version=__version__,
            developer_name="exwin maintainers",
            website="https://github.com/eavalenzuela/exwin",
            issue_url="https://github.com/eavalenzuela/exwin/issues",
            license_type=Gtk.License.MIT_X11,
            comments="Offline Windows software/game manager for Linux via Proton/Wine.",
        )
        dialog.present(self.props.active_window)

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            win = ExwinWindow(
                config=self.config,
                runtimes=self.runtimes,
                launcher=self.launcher,
                application=self,
            )
            self._tray = TrayIcon(
                icon_name="io.github.exwin",
                title="exwin",
                on_activate=lambda: GLib.idle_add(win.present),
                on_quit=lambda: GLib.idle_add(self.quit),
            )
            self._tray.start()  # no-op if no SNI watcher present
            self.hold()  # keep GLib loop alive when window is hidden
            win.connect("close-request", self._on_close_request)
        win.present()

    def _on_close_request(self, win) -> bool:  # noqa: ANN001
        if hasattr(win, "save_window_state"):
            win.save_window_state()
        if self._tray is not None and self._tray.running:
            win.set_visible(False)
            return True  # suppress default destroy
        self.release()
        return False  # allow normal close + GLib loop exit
