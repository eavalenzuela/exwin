"""Crash dialog — shown when a launched app exits quickly with a non-zero rc."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from exwin.backend.crash_detect import CrashInfo  # noqa: E402
from exwin.models import AppEntry  # noqa: E402


class CrashDialog(Adw.Dialog):
    """Surface the tail of a crashed app's log, with next-step actions."""

    def __init__(
        self,
        info: CrashInfo,
        on_rerun_debug: Callable[[AppEntry], None] | None = None,
        on_view_protondb: Callable[[AppEntry], None] | None = None,
        on_toast: Callable[[str], None] | None = None,
    ) -> None:
        title = f"{info.app.name} — Launch failed"
        super().__init__(title=title, content_width=640, content_height=520)
        self._info = info
        self._on_rerun_debug = on_rerun_debug
        self._on_view_protondb = on_view_protondb
        self._on_toast = on_toast

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        body = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        toolbar_view.set_content(body)

        # ── Summary banner ──────────────────────────────────────────────
        summary_text = self._summary_line(info)
        summary = Gtk.Label(
            label=summary_text,
            halign=Gtk.Align.START,
            wrap=True,
        )
        summary.add_css_class("heading")
        body.append(summary)

        if info.reason:
            reason_lbl = Gtk.Label(label=info.reason, halign=Gtk.Align.START, wrap=True)
            reason_lbl.add_css_class("dim-label")
            body.append(reason_lbl)

        # ── Log tail view ───────────────────────────────────────────────
        tail_heading = Gtk.Label(
            label="Last log lines:",
            halign=Gtk.Align.START,
        )
        tail_heading.add_css_class("dim-label")
        body.append(tail_heading)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        body.append(scroll)

        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_cursor_visible(False)
        text_view.set_monospace(True)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.set_margin_top(8)
        text_view.set_margin_bottom(8)
        text_view.set_margin_start(8)
        text_view.set_margin_end(8)
        text_view.get_buffer().set_text(info.log_tail or "(log is empty)")
        scroll.set_child(text_view)

        # ── Actions ─────────────────────────────────────────────────────
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_box.set_halign(Gtk.Align.END)
        body.append(action_box)

        if on_view_protondb is not None:
            protondb_btn = Gtk.Button(label="View ProtonDB")
            protondb_btn.connect("clicked", self._on_view_protondb_clicked)
            action_box.append(protondb_btn)

        open_log_btn = Gtk.Button(label="Open Log")
        open_log_btn.connect("clicked", self._on_open_log)
        action_box.append(open_log_btn)

        copy_btn = Gtk.Button(label="Copy Log")
        copy_btn.connect("clicked", self._on_copy_log)
        action_box.append(copy_btn)

        if on_rerun_debug is not None:
            rerun_btn = Gtk.Button(label="Rerun in Debug")
            rerun_btn.add_css_class("suggested-action")
            rerun_btn.connect("clicked", self._on_rerun_debug_clicked)
            action_box.append(rerun_btn)

        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda _btn: self.close())
        action_box.append(close_btn)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _summary_line(info: CrashInfo) -> str:
        runtime_name = info.runtime.name if info.runtime else "unknown runtime"
        duration = f"{info.duration_seconds:.1f}s"
        return f"Exited after {duration} with rc={info.rc} ({runtime_name})."

    def _on_open_log(self, _btn: Gtk.Button) -> None:
        try:
            subprocess.Popen(["xdg-open", str(self._info.log_path)])
        except OSError as exc:
            if self._on_toast:
                self._on_toast(f"Could not open log: {exc}")

    def _on_copy_log(self, _btn: Gtk.Button) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        clipboard = display.get_clipboard()
        clipboard.set(self._info.log_tail or "")
        if self._on_toast:
            self._on_toast("Log tail copied")

    def _on_view_protondb_clicked(self, _btn: Gtk.Button) -> None:
        if self._on_view_protondb is not None:
            self._on_view_protondb(self._info.app)
        self.close()

    def _on_rerun_debug_clicked(self, _btn: Gtk.Button) -> None:
        if self._on_rerun_debug is not None:
            self._on_rerun_debug(self._info.app)
        self.close()
