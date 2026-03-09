"""Main application window."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from datetime import UTC  # noqa: E402

from gi.repository import Adw, GObject, Gtk  # noqa: E402

from exwin.backend.app_config import load_app_config  # noqa: E402
from exwin.backend.config import Config  # noqa: E402
from exwin.backend.launcher import Launcher  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402
from exwin.backend.uninstall import uninstall_app  # noqa: E402
from exwin.db.apps import get_all_apps, update_last_launched  # noqa: E402
from exwin.db.runtimes import get_runtime  # noqa: E402
from exwin.models import AppEntry  # noqa: E402
from exwin.ui.app_detail_dialog import AppDetailDialog  # noqa: E402
from exwin.ui.install_dialog import InstallDialog  # noqa: E402
from exwin.ui.library_page import LibraryPage  # noqa: E402
from exwin.ui.settings_page import SettingsPage  # noqa: E402

# Sidebar nav items: (label, icon, stack page name)
_NAV_ITEMS = [
    ("Library", "applications-games-symbolic", "library"),
    ("Settings", "preferences-system-symbolic", "settings"),
]


class ExwinWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        config: Config,
        runtimes: list[Runtime],
        launcher: Launcher,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._config = config
        self._runtimes = runtimes
        self._launcher = launcher
        self.set_title("exwin")
        self.set_default_size(1100, 700)

        # ── Root: toast overlay ─────────────────────────────────────────
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        # ── Toolbar view (header bar + body) ────────────────────────────
        toolbar_view = Adw.ToolbarView()
        self._toast_overlay.set_child(toolbar_view)

        # ── Header bar ──────────────────────────────────────────────────
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self._sidebar_toggle = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic",
            active=True,
            tooltip_text="Toggle sidebar",
        )
        header.pack_start(self._sidebar_toggle)

        self._search_toggle = Gtk.ToggleButton(
            icon_name="system-search-symbolic",
            tooltip_text="Search library",
        )
        header.pack_end(self._search_toggle)

        install_btn = Gtk.Button(label="Install Game", tooltip_text="Install a new game")
        install_btn.add_css_class("suggested-action")
        install_btn.connect("clicked", self._on_install_clicked)
        header.pack_end(install_btn)

        # ── Body: sidebar + separator + content ─────────────────────────
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.set_vexpand(True)
        toolbar_view.set_content(body)

        self._sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._sidebar.set_size_request(180, -1)
        body.append(self._sidebar)

        self._nav_list = Gtk.ListBox()
        self._nav_list.add_css_class("navigation-sidebar")
        self._nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._nav_list.connect("row-selected", self._on_nav_row_selected)
        self._sidebar.append(self._nav_list)

        for label, icon, _page in _NAV_ITEMS:
            self._nav_list.append(_NavRow(label, icon))

        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Content stack
        self._stack = Gtk.Stack()
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        body.append(self._stack)

        self._library_page = LibraryPage(on_app_activated=self._on_app_activated)
        self._stack.add_named(self._library_page, "library")

        self._settings_page = SettingsPage(
            config=config,
            runtimes=runtimes,
            on_runtimes_changed=self._on_runtimes_changed,
        )
        self._stack.add_named(self._settings_page, "settings")

        # ── Bindings ────────────────────────────────────────────────────
        self._sidebar_toggle.bind_property(
            "active",
            self._sidebar,
            "visible",
            GObject.BindingFlags.SYNC_CREATE,
        )
        self._search_toggle.bind_property(
            "active",
            self._library_page.search_bar,
            "search-mode-enabled",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )
        self._stack.connect("notify::visible-child-name", self._on_page_changed)

        self._nav_list.select_row(self._nav_list.get_row_at_index(0))
        self.refresh_library()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def show_toast(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))

    def refresh_library(self) -> None:
        apps = get_all_apps()
        running = self._launcher.running_ids()
        self._library_page.populate(apps, running_ids=running)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_nav_row_selected(self, _list_box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        _, _icon, page_name = _NAV_ITEMS[row.get_index()]
        self._stack.set_visible_child_name(page_name)

    def _on_page_changed(self, stack: Gtk.Stack, _param) -> None:
        on_library = stack.get_visible_child_name() == "library"
        self._search_toggle.set_visible(on_library)
        if not on_library:
            self._search_toggle.set_active(False)

    def _on_app_activated(self, app: AppEntry) -> None:
        dialog = AppDetailDialog(
            app=app,
            is_running=self._launcher.is_running(app.app_id),
            config=self._config,
            runtime=self._resolve_runtime(app),
            runtimes=self._runtimes,
            on_launch=self._launch_app,
            on_stop=self._stop_app,
            on_uninstall=self._uninstall_app,
            on_settings_saved=self._on_app_config_saved,
            on_paths_changed=self._on_app_paths_changed,
        )
        dialog.present(self)

    def _on_install_clicked(self, _btn: Gtk.Button) -> None:
        dialog = InstallDialog(
            config=self._config,
            runtimes=self._runtimes,
            on_installed=self._on_app_installed,
        )
        dialog.present(self)

    def _on_app_installed(self, app: AppEntry) -> None:
        self.refresh_library()
        self.show_toast(f'"{app.name}" added to library')

    def _on_app_config_saved(self, app_id: str, app_config) -> None:  # noqa: ANN001
        self.refresh_library()
        self.show_toast("Settings saved")

    def _on_app_paths_changed(self, app: AppEntry) -> None:
        self.refresh_library()

    def _on_runtimes_changed(self) -> None:
        from exwin.backend.runtime import scan_runtimes
        from exwin.db.runtimes import sync_runtimes

        self._runtimes = sync_runtimes(scan_runtimes())
        # Rebuild settings page with updated runtimes
        self._stack.remove(self._settings_page)
        self._settings_page = SettingsPage(
            config=self._config,
            runtimes=self._runtimes,
            on_runtimes_changed=self._on_runtimes_changed,
        )
        self._stack.add_named(self._settings_page, "settings")
        self.show_toast(f"{len(self._runtimes)} runtime(s) detected")

    # ------------------------------------------------------------------
    # App lifecycle
    # ------------------------------------------------------------------

    def _launch_app(self, app: AppEntry) -> None:
        runtime = self._resolve_runtime(app)
        if runtime is None:
            self.show_toast("No Wine/Proton runtime found — add one in Settings")
            return

        app_config = load_app_config(app.app_id, self._config)

        if not app.install_path or not app.exe_path:
            self.show_toast(f'"{app.name}" has no executable configured')
            return

        self._launcher.launch(
            app=app,
            runtime=runtime,
            app_config=app_config,
            on_exit=self._on_app_exited,
        )
        self.refresh_library()
        self.show_toast(f'Launched "{app.name}"')

    def _stop_app(self, app: AppEntry) -> None:
        self._launcher.stop(app.app_id)
        self.show_toast(f'Stopping "{app.name}"…')

    def _on_app_exited(self, app_id: str) -> None:
        from datetime import datetime

        update_last_launched(app_id, datetime.now(tz=UTC).isoformat())
        self.refresh_library()

    def _uninstall_app(self, app: AppEntry, delete_files: bool) -> None:
        uninstall_app(app, self._config, delete_files)
        self.refresh_library()
        self.show_toast(f'"{app.name}" uninstalled')

    def _resolve_runtime(self, app: AppEntry) -> Runtime | None:
        """Pick the runtime for an app: app-specific first, then first available."""
        if app.runtime_id is not None:
            rt = get_runtime(app.runtime_id)
            if rt is not None:
                return rt
        return self._runtimes[0] if self._runtimes else None


# ---------------------------------------------------------------------------
# Sidebar nav row
# ---------------------------------------------------------------------------


class _NavRow(Gtk.ListBoxRow):
    def __init__(self, label: str, icon_name: str) -> None:
        super().__init__()
        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10,
            margin_top=10,
            margin_bottom=10,
            margin_start=12,
            margin_end=12,
        )
        box.append(Gtk.Image(icon_name=icon_name))
        lbl = Gtk.Label(label=label, halign=Gtk.Align.START, hexpand=True)
        box.append(lbl)
        self.set_child(box)
