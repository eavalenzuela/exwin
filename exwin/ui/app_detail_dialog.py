"""App detail dialog — shown when a library card is activated."""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from exwin.backend.app_config import AppConfig, load_app_config  # noqa: E402
from exwin.backend.config import Config  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402
from exwin.backend.saves import (  # noqa: E402
    backup_saves,
    enforce_retention,
    list_backups,
    restore_saves,
)
from exwin.models import AppEntry  # noqa: E402
from exwin.ui.library_page import _fmt_playtime  # noqa: E402


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
        on_uninstall: Callable[[AppEntry, bool], None],
        on_settings_saved: Callable[[str, AppConfig], None] | None = None,
        on_paths_changed: Callable[[AppEntry], None] | None = None,
        runtimes: list[Runtime] | None = None,
        launcher=None,  # noqa: ANN001
        **kwargs,
    ) -> None:
        super().__init__(title=app.name, content_width=440, **kwargs)
        self._app = app
        self._config = config
        self._runtime = runtime
        self._runtimes = runtimes or []
        self._on_launch = on_launch
        self._on_stop = on_stop
        self._on_uninstall = on_uninstall
        self._on_settings_saved = on_settings_saved
        self._on_paths_changed = on_paths_changed
        self._migrate_btn: Gtk.Button | None = None
        self._launcher = launcher
        self._is_running = is_running
        self._app_config = load_app_config(app.app_id, config)

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
        cover.update_property([Gtk.AccessibleProperty.LABEL], [f"Cover art for {app.name}"])
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

        self._running_label = Gtk.Label(label="· Running")
        self._running_label.add_css_class("caption")
        self._running_label.add_css_class("success")
        self._running_label.set_visible(is_running)
        status_box.append(self._running_label)

        # Description
        if app.description:
            desc = Gtk.Label(label=app.description)
            desc.set_wrap(True)
            desc.set_halign(Gtk.Align.START)
            desc.add_css_class("body")
            content.append(desc)

        # Tags
        tags_group = Adw.PreferencesGroup(title="Tags")
        content.append(tags_group)

        self._tags_row = Adw.EntryRow(title="Tags (comma-separated)")
        self._tags_row.set_text(app.tags)
        save_tags_btn = Gtk.Button(icon_name="document-save-symbolic")
        save_tags_btn.add_css_class("flat")
        save_tags_btn.set_valign(Gtk.Align.CENTER)
        save_tags_btn.set_tooltip_text("Save tags")
        save_tags_btn.connect("clicked", self._on_save_tags)
        self._tags_row.add_suffix(save_tags_btn)
        tags_group.add(self._tags_row)

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
        if app.playtime_seconds > 0:
            info_group.add(_info_row("Play Time", _fmt_playtime(app.playtime_seconds)))
        if app.install_path:
            install_dir = Path(app.install_path)
            size = _dir_size(install_dir)
            if size > 0:
                info_group.add(_info_row("Install Size", _fmt_size(size)))
            try:
                free = shutil.disk_usage(install_dir).free
                info_group.add(_info_row("Disk Free", _fmt_size(free)))
            except OSError:
                pass

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

        if config.storage_root is not None and app.install_path:
            target = config.installs_dir / app.app_id
            if Path(app.install_path).resolve() != target.resolve():
                migrate_btn = Gtk.Button(label="Move to Storage")
                migrate_btn.add_css_class("flat")
                migrate_btn.set_tooltip_text(
                    f"Move game files and Wine prefix to {config.storage_root}"
                )
                migrate_btn.connect("clicked", self._on_migrate_clicked)
                btn_box.append(migrate_btn)
                self._migrate_btn = migrate_btn

        if self._app_config.save_path:
            backup_btn = Gtk.Button(label="Back Up Saves")
            backup_btn.add_css_class("flat")
            backup_btn.connect("clicked", self._on_backup_saves)
            btn_box.append(backup_btn)

            if list_backups(app.app_id, config):
                restore_btn = Gtk.Button(label="Restore Saves")
                restore_btn.add_css_class("flat")
                restore_btn.connect("clicked", self._on_restore_saves)
                btn_box.append(restore_btn)

        # Log viewer button
        log_path = config.logs_dir / f"{app.app_id}.log"
        if log_path.exists():
            log_btn = Gtk.Button(label="View Log")
            log_btn.add_css_class("flat")
            log_btn.set_tooltip_text("View application log output")
            log_btn.connect("clicked", self._on_view_log)
            btn_box.append(log_btn)

        self._primary_btn = Gtk.Button()
        self._primary_btn.add_css_class("pill")
        self._update_primary_btn(is_running)
        btn_box.append(self._primary_btn)

        # Wine prefix tools
        if app.prefix_path and runtime:
            tools_group = Adw.PreferencesGroup(title="Prefix Tools")
            content.append(tools_group)

            tools_row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8,
                halign=Gtk.Align.CENTER,
                margin_top=4,
                margin_bottom=4,
            )
            tools_wrapper = Adw.ActionRow(title="Wine tools for this prefix")
            tools_wrapper.add_suffix(tools_row)
            tools_group.add(tools_wrapper)

            winecfg_btn = Gtk.Button(label="winecfg")
            winecfg_btn.add_css_class("flat")
            winecfg_btn.set_tooltip_text("Open Wine configuration for this prefix")
            winecfg_btn.connect("clicked", self._on_winecfg)
            tools_row.append(winecfg_btn)

            regedit_btn = Gtk.Button(label="regedit")
            regedit_btn.add_css_class("flat")
            regedit_btn.set_tooltip_text("Open Wine registry editor for this prefix")
            regedit_btn.connect("clicked", self._on_regedit)
            tools_row.append(regedit_btn)

            kill_btn = Gtk.Button(label="Kill Prefix")
            kill_btn.add_css_class("flat")
            kill_btn.add_css_class("destructive-action")
            kill_btn.set_tooltip_text("Kill all processes in this Wine prefix")
            kill_btn.connect("clicked", self._on_kill_prefix)
            tools_row.append(kill_btn)

        self._uninstall_btn = Gtk.Button(label="Uninstall")
        self._uninstall_btn.add_css_class("destructive-action")
        self._uninstall_btn.set_sensitive(not is_running)
        self._uninstall_btn.set_halign(Gtk.Align.CENTER)
        self._uninstall_btn.connect("clicked", self._on_uninstall_clicked)
        content.append(self._uninstall_btn)

        # Poll running state every 2 seconds if launcher is available
        if self._launcher is not None:
            self._poll_source = GLib.timeout_add_seconds(2, self._poll_running_state)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_save_tags(self, _btn: Gtk.Button) -> None:
        from exwin.db.apps import update_tags

        tags = self._tags_row.get_text().strip()
        update_tags(self._app.app_id, tags)
        self._app.tags = tags
        self._show_toast("Tags saved")

    def _on_settings_clicked(self, _btn: Gtk.Button) -> None:
        from exwin.ui.app_settings_dialog import AppSettingsDialog

        app_config = load_app_config(self._app.app_id, self._config)
        dialog = AppSettingsDialog(
            app=self._app,
            app_config=app_config,
            config=self._config,
            runtime=self._runtime,
            runtimes=self._runtimes,
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
        dialog = Adw.AlertDialog(
            heading="Uninstall Game?",
            body=f'Remove "{self._app.name}" from your library.',
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("keep", "Keep Files")
        dialog.add_response("delete", "Delete Files")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_uninstall_confirmed)
        dialog.present(self)

    def _on_uninstall_confirmed(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response == "cancel":
            return
        self._on_uninstall(self._app, response == "delete")
        self.close()

    def _on_open_prefix(self, _btn: Gtk.Button) -> None:
        if self._app.prefix_path:
            subprocess.Popen(["xdg-open", self._app.prefix_path])

    def _on_migrate_clicked(self, _btn: Gtk.Button) -> None:
        body = (
            f"Move game files and Wine prefix to:\n{self._config.storage_root}\n\n"
            "This may take a while for large games. The app must not be running."
        )
        if self._config.storage_root:
            try:
                free = shutil.disk_usage(self._config.storage_root).free
                body += f"\n\nFree space on target: {_fmt_size(free)}"
            except OSError:
                pass
        dialog = Adw.AlertDialog(
            heading="Move Game Data?",
            body=body,
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("move", "Move")
        dialog.set_response_appearance("move", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_migrate_confirmed)
        dialog.present(self)

    def _on_migrate_confirmed(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response != "move":
            return
        if self._migrate_btn:
            self._migrate_btn.set_label("Moving…")
            self._migrate_btn.set_sensitive(False)
        import threading

        threading.Thread(target=self._migrate_thread, daemon=True).start()

    def _migrate_thread(self) -> None:
        from gi.repository import GLib

        from exwin.backend.migrate import move_game_data

        try:
            new_app = move_game_data(self._app, self._config)
            GLib.idle_add(self._on_migrate_done, new_app)
        except Exception as exc:
            GLib.idle_add(self._on_migrate_error, str(exc))

    def _on_migrate_done(self, new_app: AppEntry) -> None:
        self._app = new_app
        if self._on_paths_changed:
            self._on_paths_changed(new_app)
        root = self.get_root()
        if hasattr(root, "show_toast"):
            root.show_toast(f'"{new_app.name}" moved to storage successfully')
        self.close()

    def _on_migrate_error(self, msg: str) -> None:
        if self._migrate_btn:
            self._migrate_btn.set_label("Move to Storage")
            self._migrate_btn.set_sensitive(True)
        root = self.get_root()
        if hasattr(root, "show_toast"):
            root.show_toast(f"Migration failed: {msg}")

    def _on_make_shortcut(self, _btn: Gtk.Button) -> None:
        from gi.repository import GLib

        from exwin.backend.desktop_shortcut import create_shortcut

        _btn.set_sensitive(False)

        def _work() -> None:
            try:
                dest = create_shortcut(self._app)
                msg = f"Shortcut created: {dest.name}"
            except Exception as exc:
                msg = f"Shortcut failed: {exc}"
            GLib.idle_add(self._show_toast_and_reenable, msg, _btn)

        threading.Thread(target=_work, daemon=True).start()

    def _on_backup_saves(self, _btn: Gtk.Button) -> None:
        from gi.repository import GLib

        _btn.set_sensitive(False)

        def _work() -> None:
            try:
                dest = backup_saves(self._app, self._app_config, self._config)
                enforce_retention(self._app.app_id, self._config)
                msg = f"Saves backed up: {dest.name}"
            except Exception as exc:
                msg = f"Backup failed: {exc}"
            GLib.idle_add(self._show_toast_and_reenable, msg, _btn)

        threading.Thread(target=_work, daemon=True).start()

    def _on_restore_saves(self, _btn: Gtk.Button) -> None:
        from gi.repository import GLib

        backups = list_backups(self._app.app_id, self._config)
        if not backups:
            return

        _btn.set_sensitive(False)

        def _work() -> None:
            try:
                restore_saves(backups[0], self._app_config)
                msg = f"Saves restored from: {backups[0].name}"
            except Exception as exc:
                msg = f"Restore failed: {exc}"
            GLib.idle_add(self._show_toast_and_reenable, msg, _btn)

        threading.Thread(target=_work, daemon=True).start()

    def _on_view_log(self, _btn: Gtk.Button) -> None:
        from exwin.ui.log_viewer_dialog import LogViewerDialog

        log_path = self._config.logs_dir / f"{self._app.app_id}.log"
        dialog = LogViewerDialog(app_name=self._app.name, log_path=log_path)
        dialog.present(self)

    def _on_winecfg(self, _btn: Gtk.Button) -> None:
        from exwin.backend.prefix_tools import run_winecfg

        if self._app.prefix_path and self._runtime:
            try:
                run_winecfg(self._app.prefix_path, self._runtime)
            except Exception as exc:
                self._show_toast(f"winecfg failed: {exc}")

    def _on_regedit(self, _btn: Gtk.Button) -> None:
        from exwin.backend.prefix_tools import run_regedit

        if self._app.prefix_path and self._runtime:
            try:
                run_regedit(self._app.prefix_path, self._runtime)
            except Exception as exc:
                self._show_toast(f"regedit failed: {exc}")

    def _on_kill_prefix(self, _btn: Gtk.Button) -> None:
        from exwin.backend.prefix_tools import kill_prefix

        if self._app.prefix_path and self._runtime:
            try:
                kill_prefix(self._app.prefix_path, self._runtime)
                self._show_toast("Prefix processes killed")
            except Exception as exc:
                self._show_toast(f"Kill prefix failed: {exc}")

    def _update_primary_btn(self, is_running: bool) -> None:
        """Reconfigure the primary action button for current running state."""
        self._primary_btn.set_label("Stop" if is_running else "Launch")
        # Remove both style classes first, then add the correct one
        self._primary_btn.remove_css_class("destructive-action")
        self._primary_btn.remove_css_class("suggested-action")
        if is_running:
            self._primary_btn.add_css_class("destructive-action")
        else:
            self._primary_btn.add_css_class("suggested-action")
        # Reconnect click handler
        try:
            self._primary_btn.disconnect_by_func(self._on_launch_clicked)
        except TypeError:
            pass
        try:
            self._primary_btn.disconnect_by_func(self._on_stop_clicked)
        except TypeError:
            pass
        if is_running:
            self._primary_btn.connect("clicked", self._on_stop_clicked)
        else:
            self._primary_btn.connect("clicked", self._on_launch_clicked)

    def _poll_running_state(self) -> bool:
        """Periodically check if the app's running state has changed."""
        if self._launcher is None:
            return False  # stop polling
        now_running = self._launcher.is_running(self._app.app_id)
        if now_running != self._is_running:
            self._is_running = now_running
            self._running_label.set_visible(now_running)
            self._update_primary_btn(now_running)
            self._uninstall_btn.set_sensitive(not now_running)
        return True  # keep polling

    def _show_toast(self, msg: str) -> None:
        root = self.get_root()
        if hasattr(root, "show_toast"):
            root.show_toast(msg)

    def _show_toast_and_reenable(self, msg: str, btn: Gtk.Button) -> None:
        btn.set_sensitive(True)
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


def _fmt_size(nbytes: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} B"
        nbytes /= 1024  # type: ignore[assignment]
    return f"{nbytes:.1f} PB"


def _dir_size(path: Path) -> int:
    """Total bytes of all files under *path*."""
    if not path.is_dir():
        return 0
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total
