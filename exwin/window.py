"""Main application window."""

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw  # noqa: E402


class ExwinWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.set_title("exwin")
        self.set_default_size(1100, 700)

        # Root layout
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        # Header bar
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # Placeholder content — replaced in M1
        placeholder = Adw.StatusPage(
            title="exwin",
            description="Your library is empty.\nInstall a game to get started.",
            icon_name="applications-games-symbolic",
        )
        toolbar_view.set_content(placeholder)
