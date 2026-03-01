"""Multi-stage installer dialog — handles both GOG (innoextract) and generic (Wine) installers."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from exwin.backend.config import Config  # noqa: E402
from exwin.backend.generic_installer import (  # noqa: E402
    detect_installer_type,
    finalize_generic_install,
    run_wine_installer,
    scan_candidate_exes,
)
from exwin.backend.gog_installer import find_innoextract, find_sibling_parts, probe  # noqa: E402
from exwin.backend.install_worker import install_gog, install_gog_dlc  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402
from exwin.backend.winetricks import is_available as winetricks_available  # noqa: E402
from exwin.db.apps import get_all_apps  # noqa: E402
from exwin.models import AppEntry  # noqa: E402

_ARCH_OPTIONS = ["win64", "win32"]


class InstallDialog(Adw.Dialog):
    """Walks the user through installing a GOG or generic Windows installer."""

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
        self._installer_parts: list[Path] = []
        self._installer_type: str = "innosetup"  # "innosetup" | "generic"
        self._wine_proc = None  # running Wine installer subprocess
        self._generic_prefix_root: Path | None = None
        self._generic_dlc_mode: bool = False
        self._generic_dlc_base_app: AppEntry | None = None

        # Load existing library entries for DLC base-game picker
        try:
            self._base_games: list[AppEntry] = get_all_apps()
        except Exception:
            self._base_games = []

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        self._header = Adw.HeaderBar()
        self._dialog_title = Adw.WindowTitle(title="Install Game", subtitle="")
        self._header.set_title_widget(self._dialog_title)
        toolbar_view.add_top_bar(self._header)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        toolbar_view.set_content(self._stack)

        self._build_welcome_page()
        self._build_confirm_page()
        self._build_confirm_generic_page()
        self._build_installing_page()
        self._build_wine_running_page()
        self._build_exe_select_page()
        self._build_done_page()
        self._build_error_page()

        self._stack.set_visible_child_name("welcome")

    # ------------------------------------------------------------------
    # Page builders
    # ------------------------------------------------------------------

    def _build_welcome_page(self) -> None:
        page = Adw.StatusPage(
            title="Install a Game",
            description="Select a Windows installer (.exe) to continue.",
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
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            box.set_halign(Gtk.Align.CENTER)
            box.append(btn)
            box.append(warn)
            page.set_child(box)

        self._stack.add_named(page, "welcome")

    def _build_confirm_page(self) -> None:
        """Confirm page for GOG/InnoSetup installers."""
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

        self._game_info_group = Adw.PreferencesGroup(title="Game")
        self._title_row = Adw.ActionRow(title="Title")
        self._gameid_row = Adw.ActionRow(title="GOG ID")
        self._lang_row = Adw.ActionRow(title="Languages")
        self._parts_row = Adw.ActionRow(title="Installer Parts")
        self._game_info_group.add(self._title_row)
        self._game_info_group.add(self._gameid_row)
        self._game_info_group.add(self._lang_row)
        self._game_info_group.add(self._parts_row)
        box.append(self._game_info_group)

        options_group = Adw.PreferencesGroup(title="Install Options")
        box.append(options_group)

        self._runtime_row = Adw.ComboRow(title="Runtime")
        rt_names = [rt.name for rt in self._runtimes] if self._runtimes else ["None detected"]
        self._runtime_row.set_model(Gtk.StringList.new(rt_names))
        self._runtime_row.set_selected(0)
        options_group.add(self._runtime_row)

        self._arch_row = Adw.ComboRow(title="Windows Architecture")
        self._arch_row.set_model(Gtk.StringList.new(_ARCH_OPTIONS))
        self._arch_row.set_selected(0)
        options_group.add(self._arch_row)

        self._winetricks_row = Adw.EntryRow(title="Winetricks Verbs")
        self._winetricks_row.set_tooltip_text("Space-separated list, e.g.: vcredist2019 dxvk")
        if not winetricks_available():
            self._winetricks_row.set_sensitive(False)
            self._winetricks_row.set_title("Winetricks Verbs (winetricks not installed)")
        options_group.add(self._winetricks_row)

        self._dlc_switch_row = Adw.SwitchRow(
            title="DLC / Add-on",
            subtitle="Install into an existing game's directory",
        )
        if not self._base_games:
            self._dlc_switch_row.set_sensitive(False)
            self._dlc_switch_row.set_subtitle("No games installed yet")
        self._dlc_switch_row.connect("notify::active", self._on_dlc_toggled)
        options_group.add(self._dlc_switch_row)

        base_names = [app.name for app in self._base_games] or ["—"]
        self._base_game_row = Adw.ComboRow(title="Base Game")
        self._base_game_row.set_model(Gtk.StringList.new(base_names))
        self._base_game_row.set_selected(0)
        self._base_game_row.set_visible(False)
        options_group.add(self._base_game_row)

        self._dxvk_row = Adw.SwitchRow(title="Install DXVK", subtitle="DirectX 9/10/11 → Vulkan")
        options_group.add(self._dxvk_row)

        self._vkd3d_row = Adw.SwitchRow(
            title="Install VKD3D-Proton", subtitle="DirectX 12 → Vulkan"
        )
        options_group.add(self._vkd3d_row)

        install_btn = Gtk.Button(label="Install")
        install_btn.add_css_class("suggested-action")
        install_btn.add_css_class("pill")
        install_btn.set_halign(Gtk.Align.CENTER)
        install_btn.connect("clicked", self._on_install_clicked)
        box.append(install_btn)

        self._stack.add_named(scroll, "confirm")

    def _build_confirm_generic_page(self) -> None:
        """Confirm page for generic (non-InnoSetup) Wine installers."""
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

        # Info banner
        info_group = Adw.PreferencesGroup(title="Installer")
        self._generic_file_row = Adw.ActionRow(title="File")
        info_group.add(self._generic_file_row)
        box.append(info_group)

        banner = Gtk.Label(
            label="This installer will run interactively via Wine.\n"
            "Interact with the Windows installer window to complete installation.",
            wrap=True,
            halign=Gtk.Align.CENTER,
        )
        banner.add_css_class("dim-label")
        banner.add_css_class("caption")
        box.append(banner)

        options_group = Adw.PreferencesGroup(title="Install Options")
        box.append(options_group)

        self._generic_runtime_row = Adw.ComboRow(title="Runtime")
        rt_names = [rt.name for rt in self._runtimes] if self._runtimes else ["None detected"]
        self._generic_runtime_row.set_model(Gtk.StringList.new(rt_names))
        self._generic_runtime_row.set_selected(0)
        options_group.add(self._generic_runtime_row)

        self._generic_arch_row = Adw.ComboRow(title="Windows Architecture")
        self._generic_arch_row.set_model(Gtk.StringList.new(_ARCH_OPTIONS))
        self._generic_arch_row.set_selected(0)
        options_group.add(self._generic_arch_row)

        self._generic_winetricks_row = Adw.EntryRow(title="Winetricks Verbs (post-install)")
        self._generic_winetricks_row.set_tooltip_text(
            "Space-separated list applied after installation"
        )
        if not winetricks_available():
            self._generic_winetricks_row.set_sensitive(False)
            self._generic_winetricks_row.set_title("Winetricks Verbs (winetricks not installed)")
        options_group.add(self._generic_winetricks_row)

        self._generic_dlc_switch_row = Adw.SwitchRow(
            title="DLC / Add-on",
            subtitle="Install into an existing game's directory",
        )
        if not self._base_games:
            self._generic_dlc_switch_row.set_sensitive(False)
            self._generic_dlc_switch_row.set_subtitle("No games installed yet")
        self._generic_dlc_switch_row.connect("notify::active", self._on_generic_dlc_toggled)
        options_group.add(self._generic_dlc_switch_row)

        generic_base_names = [app.name for app in self._base_games] or ["—"]
        self._generic_base_game_row = Adw.ComboRow(title="Base Game")
        self._generic_base_game_row.set_model(Gtk.StringList.new(generic_base_names))
        self._generic_base_game_row.set_selected(0)
        self._generic_base_game_row.set_visible(False)
        options_group.add(self._generic_base_game_row)

        self._generic_dxvk_row = Adw.SwitchRow(
            title="Install DXVK", subtitle="DirectX 9/10/11 → Vulkan"
        )
        options_group.add(self._generic_dxvk_row)

        self._generic_vkd3d_row = Adw.SwitchRow(
            title="Install VKD3D-Proton", subtitle="DirectX 12 → Vulkan"
        )
        options_group.add(self._generic_vkd3d_row)

        install_btn = Gtk.Button(label="Run Installer")
        install_btn.add_css_class("suggested-action")
        install_btn.add_css_class("pill")
        install_btn.set_halign(Gtk.Align.CENTER)
        install_btn.connect("clicked", self._on_generic_install_clicked)
        box.append(install_btn)

        self._stack.add_named(scroll, "confirm_generic")

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

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._log_buffer = Gtk.TextBuffer()
        log_view = Gtk.TextView(buffer=self._log_buffer, editable=False, monospace=True)
        log_view.add_css_class("caption")
        scroll.set_child(log_view)
        self._log_scroll = scroll
        box.append(scroll)

        self._stack.add_named(box, "installing")

    def _build_wine_running_page(self) -> None:
        page = Adw.StatusPage(
            title="Installer Running",
            description="Interact with the Windows installer window.\n"
            "exwin will continue automatically when you close it.",
            icon_name="application-x-executable-symbolic",
        )
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.add_css_class("destructive-action")
        cancel_btn.add_css_class("pill")
        cancel_btn.connect("clicked", self._on_cancel_wine)
        page.set_child(cancel_btn)
        self._stack.add_named(page, "wine_running")

    def _build_exe_select_page(self) -> None:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
            vexpand=True,
        )

        title = Gtk.Label(label="Select the main executable")
        title.add_css_class("title-3")
        title.set_halign(Gtk.Align.START)
        box.append(title)

        subtitle = Gtk.Label(label="Choose the .exe file that launches the game or application.")
        subtitle.add_css_class("dim-label")
        subtitle.set_wrap(True)
        subtitle.set_halign(Gtk.Align.START)
        box.append(subtitle)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._exe_list = Gtk.ListBox()
        self._exe_list.add_css_class("boxed-list")
        self._exe_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scroll.set_child(self._exe_list)
        box.append(scroll)

        self._exe_confirm_btn = Gtk.Button(label="Use Selected Executable")
        self._exe_confirm_btn.add_css_class("suggested-action")
        self._exe_confirm_btn.add_css_class("pill")
        self._exe_confirm_btn.set_halign(Gtk.Align.CENTER)
        self._exe_confirm_btn.set_sensitive(False)
        self._exe_confirm_btn.connect("clicked", self._on_exe_confirmed)
        box.append(self._exe_confirm_btn)

        self._exe_list.connect("row-selected", self._on_exe_row_selected)

        self._stack.add_named(box, "exe_select")

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
    # Handlers — file selection & probing
    # ------------------------------------------------------------------

    def _on_choose_clicked(self, _btn: Gtk.Button) -> None:
        f = Gtk.FileFilter()
        f.set_name("Windows Executables (*.exe)")
        f.add_pattern("*.exe")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)

        dialog = Gtk.FileDialog(title="Select Installer", filters=filters)
        dialog.open(self.get_root(), None, self._on_file_chosen)

    def _on_file_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return

        self._installer_path = Path(gfile.get_path())
        self._installer_parts = find_sibling_parts(self._installer_path)
        self._show_probing()

    def _show_probing(self) -> None:
        self._dialog_title.set_title("Reading installer…")
        self._stack.set_visible_child_name("installing")
        self._install_spinner.set_spinning(True)
        self._install_status_label.set_label("Reading installer…")
        self._log_buffer.set_text("")

        threading.Thread(target=self._probe_thread, daemon=True).start()

    def _probe_thread(self) -> None:
        assert self._installer_path is not None
        try:
            installer_type = detect_installer_type(self._installer_path)
            if installer_type == "innosetup":
                info = probe(self._installer_path)
                GLib.idle_add(self._on_probe_done, info)
            else:
                GLib.idle_add(self._on_generic_detected)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    def _on_probe_done(self, info) -> None:
        self._installer_type = "innosetup"
        self._install_spinner.set_spinning(False)
        self._dialog_title.set_title(info.title)
        self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._stack.set_visible_child_name("confirm")
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)

        self._title_row.set_subtitle(info.title)
        self._gameid_row.set_subtitle(info.game_id or "N/A")
        self._lang_row.set_subtitle(", ".join(info.languages) or "N/A")

        n = len(self._installer_parts)
        if n == 0:
            self._parts_row.set_subtitle("Single-file installer")
        else:
            self._parts_row.set_subtitle(f"Multi-part: {1 + n} files ({n} .bin parts detected)")

    def _on_generic_detected(self) -> None:
        self._installer_type = "generic"
        assert self._installer_path is not None
        self._install_spinner.set_spinning(False)
        self._dialog_title.set_title(self._installer_path.stem)
        self._generic_file_row.set_subtitle(self._installer_path.name)
        self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._stack.set_visible_child_name("confirm_generic")
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)

    # ------------------------------------------------------------------
    # Handlers — GOG install
    # ------------------------------------------------------------------

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
            if self._dlc_switch_row.get_active() and self._base_games:
                base_app = self._base_games[self._base_game_row.get_selected()]
                dlc_title = install_gog_dlc(
                    installer_path=self._installer_path,
                    base_app=base_app,
                    config=self._config,
                    runtime=runtime,
                    on_progress=lambda msg: GLib.idle_add(self._append_log, msg),
                )
                GLib.idle_add(self._on_dlc_install_done, dlc_title, base_app.name)
            else:
                app = install_gog(
                    installer_path=self._installer_path,
                    config=self._config,
                    runtime=runtime,
                    arch=arch,
                    winetricks_verbs=verbs,
                    dxvk=self._dxvk_row.get_active(),
                    vkd3d=self._vkd3d_row.get_active(),
                    on_progress=lambda msg: GLib.idle_add(self._append_log, msg),
                )
                GLib.idle_add(self._on_install_done, app)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    # ------------------------------------------------------------------
    # Handlers — generic Wine install
    # ------------------------------------------------------------------

    def _on_generic_install_clicked(self, _btn: Gtk.Button) -> None:
        assert self._installer_path is not None
        runtime = (
            self._runtimes[self._generic_runtime_row.get_selected()] if self._runtimes else None
        )
        arch = _ARCH_OPTIONS[self._generic_arch_row.get_selected()]

        if self._generic_dlc_switch_row.get_active() and self._base_games:
            base_app = self._base_games[self._generic_base_game_row.get_selected()]
            self._generic_dlc_mode = True
            self._generic_dlc_base_app = base_app
            p_root = Path(base_app.prefix_path)
        else:
            from exwin.backend.prefix import prefix_root

            self._generic_dlc_mode = False
            self._generic_dlc_base_app = None
            app_name = self._installer_path.stem
            app_id_slug = app_name.lower().replace(" ", "-")
            p_root = prefix_root(f"manual-{app_id_slug}", self._config)

        self._generic_prefix_root = p_root
        self._generic_runtime = runtime
        self._generic_arch = arch

        self._stack.set_visible_child_name("wine_running")
        threading.Thread(
            target=self._wine_installer_thread,
            args=(self._installer_path, p_root, runtime, arch),
            daemon=True,
        ).start()

    def _wine_installer_thread(self, installer: Path, p_root: Path, runtime, arch: str) -> None:
        try:
            proc = run_wine_installer(installer, p_root, runtime, arch)
            self._wine_proc = proc
            proc.wait()
            self._wine_proc = None
            GLib.idle_add(self._on_wine_installer_done)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    def _on_wine_installer_done(self) -> None:
        if self._generic_dlc_mode and self._generic_dlc_base_app is not None:
            self._done_page.set_description(
                f'DLC installed for "{self._generic_dlc_base_app.name}".'
            )
            self._stack.set_visible_child_name("done")
            return

        assert self._generic_prefix_root is not None
        candidates = scan_candidate_exes(self._generic_prefix_root, self._generic_runtime)

        # Populate the exe selection list
        while self._exe_list.get_first_child():
            self._exe_list.remove(self._exe_list.get_first_child())

        if not candidates:
            self._on_error(
                "Wine installer finished but no executable was found in the prefix.\n"
                "The installation may have failed."
            )
            return

        for exe_path in candidates:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=str(exe_path))
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            label.set_margin_start(12)
            label.set_margin_end(12)
            label.set_halign(Gtk.Align.START)
            label.set_xalign(0)
            label.set_ellipsize(3)  # END
            row.set_child(label)
            row.exe_path = exe_path  # type: ignore[attr-defined]
            self._exe_list.append(row)

        # Pre-select the first row
        self._exe_list.select_row(self._exe_list.get_row_at_index(0))
        self._exe_confirm_btn.set_sensitive(True)
        self._stack.set_visible_child_name("exe_select")

    def _on_exe_row_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        self._exe_confirm_btn.set_sensitive(row is not None)

    def _on_exe_confirmed(self, _btn: Gtk.Button) -> None:
        row = self._exe_list.get_selected_row()
        if row is None:
            return

        exe_abs: Path = row.exe_path  # type: ignore[attr-defined]
        assert self._installer_path is not None
        assert self._generic_prefix_root is not None

        app_name = self._installer_path.stem
        verbs_text = self._generic_winetricks_row.get_text().strip()
        verbs = verbs_text.split() if verbs_text else []

        self._stack.set_visible_child_name("installing")
        self._install_spinner.set_spinning(True)
        self._install_status_label.set_label("Finalising…")
        self._log_buffer.set_text("")

        threading.Thread(
            target=self._finalize_thread,
            args=(app_name, exe_abs, verbs),
            daemon=True,
        ).start()

    def _finalize_thread(self, app_name: str, exe_abs: Path, verbs: list[str]) -> None:
        assert self._generic_prefix_root is not None
        try:
            app = finalize_generic_install(
                app_name=app_name,
                p_root=self._generic_prefix_root,
                exe_abs=exe_abs,
                config=self._config,
                runtime=self._generic_runtime,
                arch=self._generic_arch,
                winetricks_verbs=verbs,
                on_progress=lambda msg: GLib.idle_add(self._append_log, msg),
            )
            GLib.idle_add(self._on_install_done, app)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    def _on_cancel_wine(self, _btn: Gtk.Button) -> None:
        if self._wine_proc is not None:
            self._wine_proc.terminate()
        self._stack.set_visible_child_name("welcome")
        self._installer_path = None
        self._dialog_title.set_title("Install Game")

    # ------------------------------------------------------------------
    # Shared handlers
    # ------------------------------------------------------------------

    def _on_dlc_toggled(self, switch_row: Adw.SwitchRow, _pspec) -> None:
        self._base_game_row.set_visible(switch_row.get_active())

    def _on_generic_dlc_toggled(self, switch_row: Adw.SwitchRow, _pspec) -> None:
        self._generic_base_game_row.set_visible(switch_row.get_active())

    def _on_install_done(self, app: AppEntry) -> None:
        self._install_spinner.set_spinning(False)
        self._done_page.set_description(f'"{app.name}" is ready to play.')
        self._stack.set_visible_child_name("done")
        self._on_installed(app)

    def _on_dlc_install_done(self, dlc_title: str, base_name: str) -> None:
        self._install_spinner.set_spinning(False)
        self._done_page.set_description(f'DLC installed for "{base_name}".')
        self._stack.set_visible_child_name("done")

    def _on_error(self, message: str) -> None:
        self._install_spinner.set_spinning(False)
        self._error_page.set_description(message)
        self._stack.set_visible_child_name("error")

    def _on_retry_clicked(self, _btn: Gtk.Button) -> None:
        self._installer_path = None
        self._dialog_title.set_title("Install Game")
        self._stack.set_visible_child_name("welcome")

    def _append_log(self, line: str) -> None:
        end = self._log_buffer.get_end_iter()
        self._log_buffer.insert(end, line + "\n")
        adj = self._log_scroll.get_vadjustment()
        adj.set_value(adj.get_upper())
