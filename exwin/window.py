"""Main application window."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GObject, Gtk  # noqa: E402

from exwin.backend.config import Config  # noqa: E402
from exwin.db.apps import delete_app, get_all_apps  # noqa: E402
from exwin.models import AppEntry  # noqa: E402
from exwin.ui.app_detail_dialog import AppDetailDialog  # noqa: E402
from exwin.ui.library_page import LibraryPage  # noqa: E402
from exwin.ui.settings_page import SettingsPage  # noqa: E402

# Sidebar nav items: (label, icon, stack page name)
_NAV_ITEMS = [
    ("Library", "applications-games-symbolic", "library"),
    ("Settings", "preferences-system-symbolic", "settings"),
]


class ExwinWindow(Adw.ApplicationWindow):
    def __init__(self, config: Config, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config = config
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

        # Sidebar toggle (left)
        self._sidebar_toggle = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic",
            active=True,
            tooltip_text="Toggle sidebar",
        )
        header.pack_start(self._sidebar_toggle)

        # Search toggle (right, only relevant in library view)
        self._search_toggle = Gtk.ToggleButton(
            icon_name="system-search-symbolic",
            tooltip_text="Search library",
        )
        header.pack_end(self._search_toggle)

        # Install button (right)
        install_btn = Gtk.Button(
            label="Install Game",
            tooltip_text="Install a new game",
        )
        install_btn.add_css_class("suggested-action")
        install_btn.connect("clicked", self._on_install_clicked)
        header.pack_end(install_btn)

        # ── Body: sidebar + separator + content ─────────────────────────
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.set_vexpand(True)
        toolbar_view.set_content(body)

        # Sidebar
        self._sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._sidebar.set_size_request(180, -1)
        body.append(self._sidebar)

        self._nav_list = Gtk.ListBox()
        self._nav_list.add_css_class("navigation-sidebar")
        self._nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._nav_list.connect("row-selected", self._on_nav_row_selected)
        self._sidebar.append(self._nav_list)

        for label, icon, _page in _NAV_ITEMS:
            row = _NavRow(label, icon)
            self._nav_list.append(row)

        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Content stack
        self._stack = Gtk.Stack()
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        body.append(self._stack)

        # Library page
        self._library_page = LibraryPage(on_app_activated=self._on_app_activated)
        self._stack.add_named(self._library_page, "library")

        # Settings page
        self._settings_page = SettingsPage(config=config)
        self._stack.add_named(self._settings_page, "settings")

        # ── Wire up sidebar toggle ───────────────────────────────────────
        self._sidebar_toggle.bind_property(
            "active",
            self._sidebar,
            "visible",
            GObject.BindingFlags.SYNC_CREATE,
        )

        # ── Wire up search toggle ────────────────────────────────────────
        # Bind toggle ↔ search bar (bidirectional)
        self._search_toggle.bind_property(
            "active",
            self._library_page.search_bar,
            "search-mode-enabled",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )
        # Hide search toggle when not on library page
        self._stack.connect("notify::visible-child-name", self._on_page_changed)

        # ── Select Library by default ────────────────────────────────────
        self._nav_list.select_row(self._nav_list.get_row_at_index(0))

        # ── Load library ─────────────────────────────────────────────────
        self.refresh_library()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def show_toast(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))

    def refresh_library(self) -> None:
        apps = get_all_apps()
        self._library_page.populate(apps)

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
            on_launch=self._launch_app,
            on_uninstall=self._uninstall_app,
        )
        dialog.present(self)

    def _on_install_clicked(self, _btn: Gtk.Button) -> None:
        # Placeholder — GOG install flow implemented in M3
        self.show_toast("Install workflow coming in M3")

    def _launch_app(self, app: AppEntry) -> None:
        # Placeholder — real launch pipeline implemented in M2
        self.show_toast(f'Launch "{app.name}" — coming in M2')

    def _uninstall_app(self, app: AppEntry) -> None:
        # TODO: confirmation dialog before delete
        delete_app(app.app_id)
        self.refresh_library()
        self.show_toast(f'"{app.name}" uninstalled')


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
