"""Multi-stage GOG installer dialog."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from exwin.backend.config import Config  # noqa: E402
from exwin.backend.gog_installer import find_innoextract, probe  # noqa: E402
from exwin.backend.install_worker import install_gog  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402
from exwin.backend.winetricks import is_available as winetricks_available  # noqa: E402
from exwin.models import AppEntry  # noqa: E402

_ARCH_OPTIONS = ["win64", "win32"]


class InstallDialog(Adw.Dialog):
    """Walks the user through installing a GOG offline installer."""

    def __init__(
        self,
        config: Config,
        runtimes: list[Runtime],
        on_installed: Callable[[AppEntry], None],
        **kwargs,
    ) -> None:
        super().__init__(title="Install Game", content_width=500, **kwargs)
        self._config = config
        self._runtimes = runtimes
        self._on_installed = on_installed
        self._installer_path: Path | None = None

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        self._header = Adw.HeaderBar()
        toolbar_view.add_top_bar(self._header)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        toolbar_view.set_content(self._stack)

        self._build_welcome_page()
        self._build_confirm_page()
        self._build_installing_page()
        self._build_done_page()
        self._build_error_page()

        self._stack.set_visible_child_name("welcome")

    # ------------------------------------------------------------------
    # Page builders
    # ------------------------------------------------------------------

    def _build_welcome_page(self) -> None:
        page = Adw.StatusPage(
            title="Install a GOG Game",
            description="Select a GOG offline installer (.exe) to continue.",
            icon_name="document-open-symbolic",
        )
        btn = Gtk.Button(label="Choose Installer…")
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.connect("clicked", self._on_choose_clicked)
        page.set_child(btn)

        try:
            find_innoextract()
        except RuntimeError as exc:
            warn = Gtk.Label(label=str(exc))
            warn.add_css_class("error")
            warn.set_wrap(True)
            warn.set_halign(Gtk.Align.CENTER)
            btn.set_sensitive(False)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            box.set_halign(Gtk.Align.CENTER)
            box.append(btn)
            box.append(warn)
            page.set_child(box)

        self._stack.add_named(page, "welcome")

    def _build_confirm_page(self) -> None:
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        scroll.set_child(box)

        # Game info banner
        self._game_info_group = Adw.PreferencesGroup(title="Game")
        self._title_row = Adw.ActionRow(title="Title")
        self._gameid_row = Adw.ActionRow(title="GOG ID")
        self._lang_row = Adw.ActionRow(title="Languages")
        self._game_info_group.add(self._title_row)
        self._game_info_group.add(self._gameid_row)
        self._game_info_group.add(self._lang_row)
        box.append(self._game_info_group)

        # Install options
        options_group = Adw.PreferencesGroup(title="Install Options")
        box.append(options_group)

        # Runtime selector
        self._runtime_row = Adw.ComboRow(title="Runtime")
        rt_names = [rt.name for rt in self._runtimes] if self._runtimes else ["None detected"]
        self._runtime_row.set_model(Gtk.StringList.new(rt_names))
        self._runtime_row.set_selected(0)
        options_group.add(self._runtime_row)

        # Arch selector
        self._arch_row = Adw.ComboRow(title="Windows Architecture")
        self._arch_row.set_model(Gtk.StringList.new(_ARCH_OPTIONS))
        self._arch_row.set_selected(0)  # win64
        options_group.add(self._arch_row)

        # Winetricks
        self._winetricks_row = Adw.EntryRow(title="Winetricks Verbs")
        self._winetricks_row.set_tooltip_text("Space-separated list, e.g.: vcredist2019 dxvk")
        if not winetricks_available():
            self._winetricks_row.set_sensitive(False)
            self._winetricks_row.set_title("Winetricks Verbs (winetricks not installed)")
        options_group.add(self._winetricks_row)

        # Install button
        install_btn = Gtk.Button(label="Install")
        install_btn.add_css_class("suggested-action")
        install_btn.add_css_class("pill")
        install_btn.set_halign(Gtk.Align.CENTER)
        install_btn.connect("clicked", self._on_install_clicked)
        box.append(install_btn)

        self._stack.add_named(scroll, "confirm")

    def _build_installing_page(self) -> None:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
            vexpand=True,
        )

        # Status row
        status_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10,
            halign=Gtk.Align.CENTER,
        )
        self._install_spinner = Gtk.Spinner()
        self._install_spinner.set_spinning(False)
        status_box.append(self._install_spinner)

        self._install_status_label = Gtk.Label(label="Installing…")
        self._install_status_label.add_css_class("heading")
        status_box.append(self._install_status_label)
        box.append(status_box)

        # Scrollable log
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._log_buffer = Gtk.TextBuffer()
        log_view = Gtk.TextView(buffer=self._log_buffer, editable=False, monospace=True)
        log_view.add_css_class("caption")
        scroll.set_child(log_view)
        self._log_scroll = scroll
        box.append(scroll)

        self._stack.add_named(box, "installing")

    def _build_done_page(self) -> None:
        self._done_page = Adw.StatusPage(
            title="Installed!",
            icon_name="emblem-ok-symbolic",
        )
        close_btn = Gtk.Button(label="Close")
        close_btn.add_css_class("pill")
        close_btn.connect("clicked", lambda _: self.close())
        self._done_page.set_child(close_btn)
        self._stack.add_named(self._done_page, "done")

    def _build_error_page(self) -> None:
        self._error_page = Adw.StatusPage(
            title="Installation Failed",
            icon_name="dialog-error-symbolic",
        )
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            halign=Gtk.Align.CENTER,
        )
        retry_btn = Gtk.Button(label="Try Again")
        retry_btn.add_css_class("pill")
        retry_btn.connect("clicked", self._on_retry_clicked)
        close_btn = Gtk.Button(label="Close")
        close_btn.add_css_class("destructive-action")
        close_btn.add_css_class("pill")
        close_btn.connect("clicked", lambda _: self.close())
        btn_box.append(retry_btn)
        btn_box.append(close_btn)
        self._error_page.set_child(btn_box)
        self._stack.add_named(self._error_page, "error")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_choose_clicked(self, _btn: Gtk.Button) -> None:
        f = Gtk.FileFilter()
        f.set_name("Windows Executables (*.exe)")
        f.add_pattern("*.exe")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)

        dialog = Gtk.FileDialog(title="Select GOG Installer", filters=filters)
        dialog.open(self.get_root(), None, self._on_file_chosen)

    def _on_file_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return  # user cancelled

        self._installer_path = Path(gfile.get_path())
        self._show_probing()

    def _show_probing(self) -> None:
        """Probe the installer in a thread, then move to confirm page."""
        # Temporarily show a spinner on the welcome page
        self._header.set_title("Reading installer…")
        self._stack.set_visible_child_name("installing")
        self._install_spinner.set_spinning(True)
        self._install_status_label.set_label("Reading installer…")
        self._log_buffer.set_text("")

        threading.Thread(target=self._probe_thread, daemon=True).start()

    def _probe_thread(self) -> None:
        assert self._installer_path is not None
        try:
            info = probe(self._installer_path)
            GLib.idle_add(self._on_probe_done, info)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    def _on_probe_done(self, info) -> None:
        self._install_spinner.set_spinning(False)
        self._header.set_title(info.title)
        self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._stack.set_visible_child_name("confirm")
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)

        # Populate confirm page
        self._title_row.set_subtitle(info.title)
        self._gameid_row.set_subtitle(info.game_id or "N/A")
        self._lang_row.set_subtitle(", ".join(info.languages) or "N/A")

    def _on_install_clicked(self, _btn: Gtk.Button) -> None:
        self._stack.set_visible_child_name("installing")
        self._install_spinner.set_spinning(True)
        self._install_status_label.set_label("Installing…")
        self._log_buffer.set_text("")

        threading.Thread(target=self._install_thread, daemon=True).start()

    def _install_thread(self) -> None:
        assert self._installer_path is not None

        runtime = self._runtimes[self._runtime_row.get_selected()] if self._runtimes else None
        arch = _ARCH_OPTIONS[self._arch_row.get_selected()]
        verbs_text = self._winetricks_row.get_text().strip()
        verbs = verbs_text.split() if verbs_text else []

        try:
            app = install_gog(
                installer_path=self._installer_path,
                config=self._config,
                runtime=runtime,
                arch=arch,
                winetricks_verbs=verbs,
                on_progress=lambda msg: GLib.idle_add(self._append_log, msg),
            )
            GLib.idle_add(self._on_install_done, app)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    def _on_install_done(self, app: AppEntry) -> None:
        self._install_spinner.set_spinning(False)
        self._done_page.set_description(f'"{app.name}" is ready to play.')
        self._stack.set_visible_child_name("done")
        self._on_installed(app)

    def _on_error(self, message: str) -> None:
        self._install_spinner.set_spinning(False)
        self._error_page.set_description(message)
        self._stack.set_visible_child_name("error")

    def _on_retry_clicked(self, _btn: Gtk.Button) -> None:
        self._installer_path = None
        self._header.set_title("Install Game")
        self._stack.set_visible_child_name("welcome")

    def _append_log(self, line: str) -> None:
        end = self._log_buffer.get_end_iter()
        self._log_buffer.insert(end, line + "\n")
        # Scroll to bottom
        adj = self._log_scroll.get_vadjustment()
        adj.set_value(adj.get_upper())
