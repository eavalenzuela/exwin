"""Settings page — AdwPreferencesPage for global configuration."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from shutil import which as shutil_which

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk  # noqa: E402

from exwin.backend.config import Config  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402

_COLOR_SCHEMES = [
    ("System", Adw.ColorScheme.DEFAULT, "system"),
    ("Light", Adw.ColorScheme.FORCE_LIGHT, "light"),
    ("Dark", Adw.ColorScheme.FORCE_DARK, "dark"),
]


class SettingsPage(Adw.PreferencesPage):
    """Global preferences panel."""

    def __init__(
        self,
        config: Config,
        runtimes: list[Runtime],
        on_runtimes_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._on_runtimes_changed = on_runtimes_changed

        # ── General group ────────────────────────────────────────────────
        general = Adw.PreferencesGroup(title="General")
        self.add(general)

        # Data directory
        dir_row = Adw.ActionRow(
            title="Data Directory",
            subtitle=str(config.data_dir),
        )
        dir_row.set_subtitle_selectable(True)
        open_btn = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        open_btn.add_css_class("flat")
        open_btn.set_tooltip_text("Open in file manager")
        open_btn.connect("clicked", self._on_open_data_dir)
        dir_row.add_suffix(open_btn)
        general.add(dir_row)

        # Storage root availability warning
        if config.storage_root and not config.storage_root_available:
            self._storage_warn_banner = Adw.Banner(
                title="Storage root is not accessible — external drive may be unmounted. "
                "Installs and launches that depend on it will fail.",
                button_label="",
            )
            self._storage_warn_banner.set_revealed(True)
            general.add(self._storage_warn_banner)

        # Games storage root (covers both installs and prefixes)
        prefix_row = Adw.EntryRow(title="Games Storage Directory")
        prefix_row.set_text(str(config.storage_root) if config.storage_root else "")
        prefix_row.set_tooltip_text(
            "Root folder for all new game installs and Wine prefixes. "
            "Leave blank to use the default (data_dir/). "
            "Existing installs are unaffected."
        )
        browse_btn = Gtk.Button(icon_name="folder-open-symbolic")
        browse_btn.add_css_class("flat")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.connect("clicked", self._on_browse_prefix_root)
        prefix_row.add_suffix(browse_btn)
        clear_btn = Gtk.Button(icon_name="edit-clear-symbolic")
        clear_btn.add_css_class("flat")
        clear_btn.set_valign(Gtk.Align.CENTER)
        clear_btn.set_tooltip_text("Reset to default")
        clear_btn.connect("clicked", self._on_clear_prefix_root, prefix_row)
        prefix_row.add_suffix(clear_btn)
        prefix_row.connect("notify::text", self._on_prefix_root_changed)
        general.add(prefix_row)
        self._prefix_row = prefix_row

        # Color scheme
        scheme_row = Adw.ComboRow(title="Color Scheme")
        scheme_row.set_model(Gtk.StringList.new([label for label, _, _ in _COLOR_SCHEMES]))
        saved = config.color_scheme
        initial = next((i for i, (_, _, key) in enumerate(_COLOR_SCHEMES) if key == saved), 0)
        scheme_row.set_selected(initial)
        scheme_row.connect("notify::selected", self._on_color_scheme_changed)
        general.add(scheme_row)

        # ── Backups group ─────────────────────────────────────────────────
        backup_group = Adw.PreferencesGroup(title="Save Backups")
        self.add(backup_group)

        self._retention_row = Adw.SpinRow.new_with_range(0, 100, 1)
        self._retention_row.set_title("Max Backups Per Game")
        self._retention_row.set_subtitle("0 = unlimited")
        self._retention_row.set_value(config.backup_max_count)
        self._retention_row.connect("notify::value", self._on_backup_max_changed)
        backup_group.add(self._retention_row)

        # ── Wine / Proton group ──────────────────────────────────────────
        wine_group = Adw.PreferencesGroup(title="Wine / Proton")
        self.add(wine_group)

        if not runtimes:
            wine_group.set_description(
                "No runtimes detected. Install Proton via Steam or Wine via your package manager."
            )
            wine_group.add(
                Adw.ActionRow(
                    title="No runtimes found",
                    subtitle="Steam Proton and/or system Wine will appear here once available.",
                )
            )
        else:
            wine_group.set_description(
                f"{len(runtimes)} runtime(s) detected. "
                "The first entry is used by default when no per-app runtime is set."
            )

            for rt in runtimes:
                row = Adw.ActionRow(title=rt.name, subtitle=rt.version or rt.type.capitalize())
                icon = (
                    "media-playback-start-symbolic"
                    if rt.is_proton
                    else "application-x-executable-symbolic"
                )
                row.add_prefix(Gtk.Image(icon_name=icon, pixel_size=16))
                wine_group.add(row)

        # Proton-GE download row — always shown
        ge_row = Adw.ActionRow(
            title="Proton-GE",
            subtitle="Download the latest GE-Proton release",
        )
        ge_row.add_prefix(Gtk.Image(icon_name="software-update-available-symbolic", pixel_size=16))
        ge_btn = Gtk.Button(label="Download…", valign=Gtk.Align.CENTER)
        ge_btn.add_css_class("flat")
        ge_btn.connect("clicked", self._on_download_ge_clicked)
        ge_row.add_suffix(ge_btn)
        wine_group.add(ge_row)

        # umu-launcher row
        from exwin.backend import umu

        umu_path = shutil_which("umu-run")
        if umu_path:
            umu_subtitle = f"Found at {umu_path}"
        else:
            umu_subtitle = "Not installed — falling back to direct Proton"
        self._umu_row = Adw.SwitchRow(
            title="Use umu-launcher when available",
            subtitle=umu_subtitle,
        )
        self._umu_row.set_active(config.use_umu and umu.is_available())
        self._umu_row.set_sensitive(umu.is_available())
        self._umu_row.connect("notify::active", self._on_use_umu_changed)
        wine_group.add(self._umu_row)

        # Sleep/idle inhibit while a game runs
        inhibit_available = shutil_which("systemd-inhibit") is not None
        if inhibit_available:
            inhibit_subtitle = "Hold a systemd idle/sleep inhibitor while a game is running"
        else:
            inhibit_subtitle = "systemd-inhibit not found — inhibitor will be skipped"
        self._inhibit_row = Adw.SwitchRow(
            title="Prevent sleep during play",
            subtitle=inhibit_subtitle,
        )
        self._inhibit_row.set_active(config.inhibit_idle and inhibit_available)
        self._inhibit_row.set_sensitive(inhibit_available)
        self._inhibit_row.connect("notify::active", self._on_inhibit_idle_changed)
        wine_group.add(self._inhibit_row)

        # ── About group ──────────────────────────────────────────────────
        from exwin import __version__

        about_group = Adw.PreferencesGroup(title="About")
        self.add(about_group)

        self._version_row = Adw.ActionRow(title="exwin", subtitle=f"Version {__version__}")
        self._version_row.add_prefix(Gtk.Image(icon_name="help-about-symbolic", pixel_size=16))
        about_btn = Gtk.Button(label="Details…", valign=Gtk.Align.CENTER)
        about_btn.add_css_class("flat")
        about_btn.set_action_name("app.about")
        self._version_row.add_suffix(about_btn)
        about_group.add(self._version_row)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_open_data_dir(self, _btn: Gtk.Button) -> None:
        subprocess.Popen(["xdg-open", str(self._config.data_dir)])

    def _on_prefix_root_changed(self, row: Adw.EntryRow, _param) -> None:
        v = row.get_text().strip()
        self._config.storage_root = Path(v) if v else None
        self._config.save()

    def _on_browse_prefix_root(self, _btn: Gtk.Button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Select Prefix Storage Directory")
        dialog.select_folder(self.get_root(), None, self._on_browse_prefix_root_done)

    def _on_browse_prefix_root_done(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except Exception:
            return
        if folder:
            self._prefix_row.set_text(folder.get_path())

    def _on_clear_prefix_root(self, _btn: Gtk.Button, row: Adw.EntryRow) -> None:
        row.set_text("")

    def _on_color_scheme_changed(self, row: Adw.ComboRow, _param) -> None:
        _, scheme, key = _COLOR_SCHEMES[row.get_selected()]
        Adw.StyleManager.get_default().set_color_scheme(scheme)
        self._config.color_scheme = key
        self._config.save()

    def _on_backup_max_changed(self, row: Adw.SpinRow, _param) -> None:
        self._config.backup_max_count = int(row.get_value())
        self._config.save()

    def _on_use_umu_changed(self, row: Adw.SwitchRow, _param) -> None:
        self._config.use_umu = bool(row.get_active())
        self._config.save()

    def _on_inhibit_idle_changed(self, row: Adw.SwitchRow, _param) -> None:
        self._config.inhibit_idle = bool(row.get_active())
        self._config.save()

    def _on_download_ge_clicked(self, _btn: Gtk.Button) -> None:
        from exwin.ui.proton_ge_dialog import ProtonGEDialog

        def _on_installed() -> None:
            if self._on_runtimes_changed:
                self._on_runtimes_changed()

        dialog = ProtonGEDialog(on_installed=_on_installed)
        dialog.present(self.get_root())
