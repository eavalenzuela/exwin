"""Settings page — AdwPreferencesPage for global configuration."""

from __future__ import annotations

import subprocess

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk  # noqa: E402

from exwin.backend.config import Config  # noqa: E402

_COLOR_SCHEMES = [
    ("System", Adw.ColorScheme.DEFAULT),
    ("Light", Adw.ColorScheme.FORCE_LIGHT),
    ("Dark", Adw.ColorScheme.FORCE_DARK),
]


class SettingsPage(Adw.PreferencesPage):
    """Global preferences panel."""

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config

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

        # Color scheme
        scheme_row = Adw.ComboRow(title="Color Scheme")
        scheme_row.set_model(Gtk.StringList.new([label for label, _ in _COLOR_SCHEMES]))
        scheme_row.set_selected(0)
        scheme_row.connect("notify::selected", self._on_color_scheme_changed)
        general.add(scheme_row)

        # ── Wine / Proton group ──────────────────────────────────────────
        wine_group = Adw.PreferencesGroup(
            title="Wine / Proton",
            description="Runtime configuration — managed automatically in M2.",
        )
        self.add(wine_group)

        runtime_row = Adw.ActionRow(
            title="Default Runtime",
            subtitle=config.default_runtime or "Auto-detect (not yet configured)",
        )
        wine_group.add(runtime_row)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_open_data_dir(self, _btn: Gtk.Button) -> None:
        subprocess.Popen(["xdg-open", str(self._config.data_dir)])

    def _on_color_scheme_changed(self, row: Adw.ComboRow, _param) -> None:
        _, scheme = _COLOR_SCHEMES[row.get_selected()]
        Adw.StyleManager.get_default().set_color_scheme(scheme)
