"""Log viewer dialog — displays the log file for a given app."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk  # noqa: E402


class LogViewerDialog(Adw.Dialog):
    """Scrollable text view showing the contents of an app's log file."""

    def __init__(self, app_name: str, log_path: Path, **kwargs) -> None:
        super().__init__(title=f"{app_name} — Log", content_width=600, content_height=500, **kwargs)

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        if log_path.exists():
            text = log_path.read_text(errors="replace")
        else:
            text = "(no log file found)"

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        toolbar_view.set_content(scroll)

        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_cursor_visible(False)
        text_view.set_monospace(True)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.set_margin_top(8)
        text_view.set_margin_bottom(8)
        text_view.set_margin_start(8)
        text_view.set_margin_end(8)
        text_view.get_buffer().set_text(text)
        scroll.set_child(text_view)

        # Scroll to bottom after the widget is realized
        text_view.connect("realize", self._scroll_to_end, scroll)

    @staticmethod
    def _scroll_to_end(text_view: Gtk.TextView, scroll: Gtk.ScrolledWindow) -> None:
        adj = scroll.get_vadjustment()
        adj.set_value(adj.get_upper())
