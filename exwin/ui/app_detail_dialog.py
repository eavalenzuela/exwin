"""App detail dialog — shown when a library card is activated."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk  # noqa: E402

from exwin.backend.app_config import AppConfig, load_app_config  # noqa: E402
from exwin.backend.config import Config  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402
from exwin.models import AppEntry  # noqa: E402


class AppDetailDialog(Adw.Dialog):
    """Modal dialog showing full info for a single app with action buttons."""

    def __init__(
        self,
        app: AppEntry,
        is_running: bool,
        config: Config,
        runtime: Runtime | None,
        on_launch: Callable[[AppEntry], None],
        on_stop: Callable[[AppEntry], None],
        on_uninstall: Callable[[AppEntry], None],
        on_settings_saved: Callable[[str, AppConfig], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(title=app.name, content_width=440, content_height=560, **kwargs)
        self._app = app
        self._config = config
        self._runtime = runtime
        self._on_launch = on_launch
        self._on_stop = on_stop
        self._on_uninstall = on_uninstall
        self._on_settings_saved = on_settings_saved

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        settings_btn = Gtk.Button(icon_name="preferences-system-symbolic")
        settings_btn.add_css_class("flat")
        settings_btn.set_tooltip_text("App Settings")
        settings_btn.connect("clicked", self._on_settings_clicked)
        header.pack_end(settings_btn)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar_view.set_content(scroll)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)
        scroll.set_child(content)

        # Cover art
        if app.cover_art_path and Path(app.cover_art_path).exists():
            cover: Gtk.Widget = Gtk.Picture.new_for_filename(app.cover_art_path)
            cover.set_content_fit(Gtk.ContentFit.CONTAIN)  # type: ignore[attr-defined]
        else:
            cover = Gtk.Image()
            cover.set_from_icon_name("applications-games-symbolic")
            cover.set_pixel_size(96)
        cover.set_size_request(160, 220)
        cover.set_halign(Gtk.Align.CENTER)
        content.append(cover)

        # Name
        name_label = Gtk.Label(label=app.name)
        name_label.add_css_class("title-1")
        name_label.set_wrap(True)
        name_label.set_halign(Gtk.Align.CENTER)
        content.append(name_label)

        # Status / source row
        status_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            halign=Gtk.Align.CENTER,
        )
        content.append(status_box)

        source_label = Gtk.Label(label=app.source.upper())
        source_label.add_css_class("caption")
        source_label.add_css_class("dim-label")
        status_box.append(source_label)

        if is_running:
            running_label = Gtk.Label(label="· Running")
            running_label.add_css_class("caption")
            running_label.add_css_class("success")
            status_box.append(running_label)

        # Description
        if app.description:
            desc = Gtk.Label(label=app.description)
            desc.set_wrap(True)
            desc.set_halign(Gtk.Align.START)
            desc.add_css_class("body")
            content.append(desc)

        # Info rows (paths, dates)
        info_group = Adw.PreferencesGroup()
        content.append(info_group)

        if app.install_path:
            info_group.add(_info_row("Install Path", app.install_path, copyable=True))
        if app.prefix_path:
            info_group.add(_info_row("Wine Prefix", app.prefix_path, copyable=True))
        if app.install_date:
            info_group.add(_info_row("Installed", app.install_date[:10]))
        if app.last_launched:
            info_group.add(_info_row("Last Launched", app.last_launched[:10]))

        # Action buttons
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER
        )
        content.append(btn_box)

        open_btn = Gtk.Button(label="Open Prefix")
        open_btn.add_css_class("flat")
        open_btn.set_sensitive(bool(app.prefix_path))
        open_btn.connect("clicked", self._on_open_prefix)
        btn_box.append(open_btn)

        shortcut_btn = Gtk.Button(label="Shortcut")
        shortcut_btn.add_css_class("flat")
        shortcut_btn.set_tooltip_text("Create a desktop shortcut for this app")
        shortcut_btn.connect("clicked", self._on_make_shortcut)
        btn_box.append(shortcut_btn)

        if is_running:
            primary_btn = Gtk.Button(label="Stop")
            primary_btn.add_css_class("destructive-action")
            primary_btn.add_css_class("pill")
            primary_btn.connect("clicked", self._on_stop_clicked)
        else:
            primary_btn = Gtk.Button(label="Launch")
            primary_btn.add_css_class("suggested-action")
            primary_btn.add_css_class("pill")
            primary_btn.connect("clicked", self._on_launch_clicked)
        btn_box.append(primary_btn)

        uninstall_btn = Gtk.Button(label="Uninstall")
        uninstall_btn.add_css_class("destructive-action")
        uninstall_btn.set_sensitive(not is_running)
        uninstall_btn.set_halign(Gtk.Align.CENTER)
        uninstall_btn.connect("clicked", self._on_uninstall_clicked)
        content.append(uninstall_btn)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_settings_clicked(self, _btn: Gtk.Button) -> None:
        from exwin.ui.app_settings_dialog import AppSettingsDialog

        app_config = load_app_config(self._app.app_id, self._config)
        dialog = AppSettingsDialog(
            app=self._app,
            app_config=app_config,
            config=self._config,
            runtime=self._runtime,
            on_saved=self._on_app_settings_saved,
        )
        dialog.present(self.get_root())

    def _on_app_settings_saved(self, app_config: AppConfig) -> None:
        if self._on_settings_saved:
            self._on_settings_saved(self._app.app_id, app_config)

    def _on_launch_clicked(self, _btn: Gtk.Button) -> None:
        self._on_launch(self._app)
        self.close()

    def _on_stop_clicked(self, _btn: Gtk.Button) -> None:
        self._on_stop(self._app)
        self.close()

    def _on_uninstall_clicked(self, _btn: Gtk.Button) -> None:
        self._on_uninstall(self._app)
        self.close()

    def _on_open_prefix(self, _btn: Gtk.Button) -> None:
        if self._app.prefix_path:
            subprocess.Popen(["xdg-open", self._app.prefix_path])

    def _on_make_shortcut(self, _btn: Gtk.Button) -> None:
        from exwin.backend.desktop_shortcut import create_shortcut

        try:
            dest = create_shortcut(self._app)
            msg = f"Shortcut created: {dest.name}"
        except Exception as exc:
            msg = f"Shortcut failed: {exc}"
        root = self.get_root()
        if hasattr(root, "show_toast"):
            root.show_toast(msg)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _info_row(title: str, value: str, *, copyable: bool = False) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=value)
    row.set_subtitle_selectable(copyable)
    return row
