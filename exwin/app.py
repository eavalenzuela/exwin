"""Top-level Adw.Application."""

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio  # noqa: E402

from exwin.backend.config import Config  # noqa: E402
from exwin.db.schema import init_db  # noqa: E402
from exwin.window import ExwinWindow  # noqa: E402

APP_ID = "io.github.exwin"


class ExwinApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.config = Config.load()
        init_db(self.config.data_dir)

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            win = ExwinWindow(application=self)
        win.present()
