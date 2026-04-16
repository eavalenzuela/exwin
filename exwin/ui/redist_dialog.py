"""Standalone redistributable scanner / applier dialog.

Triggered by the 'Check Prereqs' button in :class:`AppDetailDialog` for
already-installed games.  The install-time flow has its own redist page
baked into :class:`InstallDialog`; this dialog just exposes the same
capability post-hoc.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from exwin.backend.redist_scanner import RedistFinding, apply_finding, scan  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402
from exwin.models import AppEntry  # noqa: E402


class RedistDialog(Adw.Dialog):
    """Scan an installed game's files for bundled redistributables."""

    def __init__(
        self,
        app: AppEntry,
        runtime: Runtime,
        on_toast: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(title="Check Prerequisites", content_width=520, content_height=560)
        self._app = app
        self._runtime = runtime
        self._on_toast = on_toast
        self._findings: list[RedistFinding] = []
        self._checks: dict[str, Gtk.CheckButton] = {}

        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)
        toolbar.add_top_bar(Adw.HeaderBar())

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        toolbar.set_content(self._stack)

        self._build_scanning_page()
        self._build_results_page()
        self._build_empty_page()
        self._build_applying_page()
        self._build_done_page()

        self._stack.set_visible_child_name("scanning")
        threading.Thread(target=self._scan_thread, daemon=True).start()

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def _build_scanning_page(self) -> None:
        page = Adw.StatusPage(title="Scanning install dir…")
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        spinner.set_halign(Gtk.Align.CENTER)
        page.set_child(spinner)
        self._stack.add_named(page, "scanning")

    def _build_results_page(self) -> None:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
            vexpand=True,
        )

        header = Gtk.Label(xalign=0, wrap=True)
        header.add_css_class("title-4")
        self._results_header = header
        box.append(header)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._results_list = Gtk.ListBox()
        self._results_list.add_css_class("boxed-list")
        self._results_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.set_child(self._results_list)
        box.append(scroll)

        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER
        )
        cancel = Gtk.Button(label="Close")
        cancel.add_css_class("pill")
        cancel.connect("clicked", lambda _: self.close())
        btn_box.append(cancel)

        apply_btn = Gtk.Button(label="Apply Selected")
        apply_btn.add_css_class("suggested-action")
        apply_btn.add_css_class("pill")
        apply_btn.connect("clicked", self._on_apply_clicked)
        btn_box.append(apply_btn)
        box.append(btn_box)

        self._stack.add_named(box, "results")

    def _build_empty_page(self) -> None:
        page = Adw.StatusPage(
            title="No prerequisites found",
            description="No bundled vcredist/DirectX/UE prereqs detected in the install dir.",
            icon_name="emblem-ok-symbolic",
        )
        close = Gtk.Button(label="Close")
        close.add_css_class("pill")
        close.connect("clicked", lambda _: self.close())
        page.set_child(close)
        self._stack.add_named(page, "empty")

    def _build_applying_page(self) -> None:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
            margin_top=24,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
            valign=Gtk.Align.CENTER,
        )
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        spinner.set_halign(Gtk.Align.CENTER)
        box.append(spinner)
        self._applying_label = Gtk.Label(label="Applying…")
        self._applying_label.add_css_class("title-4")
        self._applying_label.set_wrap(True)
        box.append(self._applying_label)
        self._stack.add_named(box, "applying")

    def _build_done_page(self) -> None:
        page = Adw.StatusPage(title="Done", icon_name="emblem-ok-symbolic")
        close = Gtk.Button(label="Close")
        close.add_css_class("pill")
        close.connect("clicked", lambda _: self.close())
        page.set_child(close)
        self._stack.add_named(page, "done")

    # ------------------------------------------------------------------
    # Scan + apply
    # ------------------------------------------------------------------

    def _scan_thread(self) -> None:
        try:
            findings = scan(self._app.install_path) if self._app.install_path else []
        except Exception:
            findings = []
        GLib.idle_add(self._on_scan_done, findings)

    def _on_scan_done(self, findings: list[RedistFinding]) -> None:
        self._findings = findings
        if not findings:
            self._stack.set_visible_child_name("empty")
            return

        self._results_header.set_label(
            f"Found {len(findings)} bundled prerequisite{'s' if len(findings) != 1 else ''}"
        )
        while (child := self._results_list.get_first_child()) is not None:
            self._results_list.remove(child)
        self._checks = {}
        for finding in findings:
            row = Adw.ActionRow(title=finding.description, subtitle=finding.path.name)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.set_active(finding.recommended)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            tag_label = Gtk.Label(
                label=("verb: " + finding.payload) if finding.action == "verb" else "run installer",
                valign=Gtk.Align.CENTER,
            )
            tag_label.add_css_class("caption")
            tag_label.add_css_class("dim-label")
            row.add_suffix(tag_label)
            self._results_list.append(row)
            self._checks[finding.kind] = check
        self._stack.set_visible_child_name("results")

    def _on_apply_clicked(self, _btn: Gtk.Button) -> None:
        selected = [f for f in self._findings if self._checks[f.kind].get_active()]
        if not selected:
            self.close()
            return
        self._stack.set_visible_child_name("applying")
        threading.Thread(target=self._apply_thread, args=(selected,), daemon=True).start()

    def _apply_thread(self, findings: list[RedistFinding]) -> None:
        prefix_root = self._app.prefix_path
        for f in findings:
            GLib.idle_add(self._applying_label.set_label, f"Applying: {f.description}")
            try:
                apply_finding(f, prefix_root, self._runtime)
            except Exception as exc:
                GLib.idle_add(self._applying_label.set_label, f"Failed: {f.description} ({exc})")
        GLib.idle_add(self._finish)

    def _finish(self) -> None:
        self._stack.set_visible_child_name("done")
        if self._on_toast:
            self._on_toast("Prerequisites applied")
