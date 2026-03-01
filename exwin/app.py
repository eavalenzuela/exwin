"""Top-level Adw.Application."""

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio  # noqa: E402

from exwin.backend.config import Config  # noqa: E402
from exwin.backend.launcher import Launcher  # noqa: E402
from exwin.backend.runtime import scan_runtimes  # noqa: E402
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

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            win = ExwinWindow(
                config=self.config,
                runtimes=self.runtimes,
                launcher=self.launcher,
                application=self,
            )
        win.present()
