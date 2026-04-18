"""Per-app configuration editor dialog."""

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

from exwin.backend.app_config import (  # noqa: E402
    AppConfig,
    GamescopeConfig,
    HookConfig,
    save_app_config,
)
from exwin.backend.config import Config  # noqa: E402
from exwin.backend.gog_metadata import apply_custom_cover_art  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402
from exwin.backend.winetricks import is_available as winetricks_available  # noqa: E402
from exwin.backend.winetricks import run_verbs  # noqa: E402
from exwin.models import AppEntry  # noqa: E402
from exwin.ui.winetricks_picker import WinetricksRow  # noqa: E402

_ARCH_OPTIONS = ["win64", "win32"]


class AppSettingsDialog(Adw.Dialog):
    """Edit per-app configuration (exe path, Wine options, env vars, etc.)."""

    def __init__(
        self,
        app: AppEntry,
        app_config: AppConfig,
        config: Config,
        runtime: Runtime | None,
        on_saved: Callable[[AppConfig], None],
        runtimes: list[Runtime] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            title=f"{app.name} — Settings", content_width=520, content_height=560, **kwargs
        )
        self._app = app
        self._app_config = app_config
        self._config = config
        self._runtime = runtime
        self._runtimes = runtimes or []
        self._on_saved = on_saved

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar_view.set_content(scroll)

        prefs = Adw.PreferencesPage()
        scroll.set_child(prefs)

        self._build_executable_group(prefs, app, app_config)
        self._build_runtime_group(prefs, app)
        self._build_wine_group(prefs, app_config)
        self._build_launch_group(prefs, app_config)
        self._build_gpu_group(prefs, app_config)
        self._build_gamescope_group(prefs, app_config)
        self._build_saves_group(prefs, app_config)
        self._build_hooks_group(prefs, app_config)
        self._build_cover_art_group(prefs, app)
        self._build_env_group(prefs, app_config)
        self._build_dll_group(prefs, app_config)
        self._build_action_row(toolbar_view)

        # Snapshot initial state for dirty tracking
        self._initial_state = self._snapshot()
        self.connect("close-attempt", self._on_close_attempt)

    # ------------------------------------------------------------------
    # Group builders
    # ------------------------------------------------------------------

    def _build_executable_group(
        self, prefs: Adw.PreferencesPage, app: AppEntry, cfg: AppConfig
    ) -> None:
        group = Adw.PreferencesGroup(title="Executable")
        prefs.add(group)

        self._exe_row = Adw.EntryRow(title="Executable path")
        self._exe_row.set_text(app.exe_path or "")
        self._exe_row.set_tooltip_text(
            "Path to the main executable, relative to the install directory"
        )

        browse_btn = Gtk.Button(icon_name="document-open-symbolic")
        browse_btn.add_css_class("flat")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.connect("clicked", self._on_browse_exe)
        self._exe_row.add_suffix(browse_btn)
        group.add(self._exe_row)

    def _build_runtime_group(self, prefs: Adw.PreferencesPage, app: AppEntry) -> None:
        group = Adw.PreferencesGroup(title="Runtime")
        prefs.add(group)

        if not self._runtimes:
            info_row = Adw.ActionRow(
                title="No runtimes detected",
                subtitle="Add a Wine or Proton runtime in Settings",
            )
            group.add(info_row)
            self._runtime_row = None
            return

        options = [rt.name for rt in self._runtimes]
        self._runtime_row = Adw.ComboRow(
            title="Wine / Proton Runtime",
            subtitle="Select the runtime to use for this game",
        )
        self._runtime_row.set_model(Gtk.StringList.new(options))

        # Select the runtime currently assigned to this app
        selected = 0
        if app.runtime_id is not None:
            for i, rt in enumerate(self._runtimes):
                if rt.db_id == app.runtime_id:
                    selected = i
                    break
        self._runtime_row.set_selected(selected)
        group.add(self._runtime_row)

    def _build_wine_group(self, prefs: Adw.PreferencesPage, cfg: AppConfig) -> None:
        group = Adw.PreferencesGroup(title="Wine / Proton")
        prefs.add(group)

        self._arch_row = Adw.ComboRow(title="Architecture")
        self._arch_row.set_model(Gtk.StringList.new(_ARCH_OPTIONS))
        self._arch_row.set_selected(0 if cfg.arch == "win64" else 1)
        group.add(self._arch_row)

        self._dxvk_row = Adw.SwitchRow(
            title="DXVK",
            subtitle="DirectX 9/10/11 → Vulkan translation (requires winetricks)",
        )
        self._dxvk_row.set_active(cfg.dxvk)
        group.add(self._dxvk_row)

        self._vkd3d_row = Adw.SwitchRow(
            title="VKD3D-Proton",
            subtitle="DirectX 12 → Vulkan translation",
        )
        self._vkd3d_row.set_active(cfg.vkd3d)
        group.add(self._vkd3d_row)

        self._winetricks_row = WinetricksRow(title="Winetricks verbs", parent=self)
        self._winetricks_row.set_text(" ".join(cfg.winetricks_verbs))
        self._winetricks_row.set_tooltip_text("Pick verbs to apply (e.g. vcrun2019, dxvk)")
        if not winetricks_available():
            self._winetricks_row.set_sensitive(False)
            self._winetricks_row.set_title("Winetricks verbs (winetricks not installed)")
        group.add(self._winetricks_row)

    def _build_launch_group(self, prefs: Adw.PreferencesPage, cfg: AppConfig) -> None:
        group = Adw.PreferencesGroup(title="Launch Options")
        prefs.add(group)

        self._gamemode_row = Adw.SwitchRow(
            title="Gamemode",
            subtitle="Run via gamemoderun for CPU scheduling optimisations",
        )
        self._gamemode_row.set_active(cfg.gamemode)
        group.add(self._gamemode_row)

        self._mangohud_row = Adw.SwitchRow(
            title="MangoHud",
            subtitle="Overlay FPS and hardware stats",
        )
        self._mangohud_row.set_active(cfg.mangohud)
        group.add(self._mangohud_row)

        self._args_row = Adw.EntryRow(title="Extra launch arguments")
        self._args_row.set_text(" ".join(cfg.launch_args))
        self._args_row.set_tooltip_text("Space-separated arguments passed to the executable")
        group.add(self._args_row)

        # umu-launcher override (tri-state)
        self._umu_options = ["Default (follow global)", "Force on", "Force off"]
        self._umu_row = Adw.ComboRow(
            title="umu-launcher",
            subtitle="Canonical Proton entry with ProtonFixes per-app support",
        )
        self._umu_row.set_model(Gtk.StringList.new(self._umu_options))
        if cfg.use_umu is None:
            self._umu_row.set_selected(0)
        elif cfg.use_umu:
            self._umu_row.set_selected(1)
        else:
            self._umu_row.set_selected(2)
        group.add(self._umu_row)

    def _build_gpu_group(self, prefs: Adw.PreferencesPage, cfg: AppConfig) -> None:
        group = Adw.PreferencesGroup(title="GPU")
        prefs.add(group)

        from exwin.backend.gpu import detect_gpus

        self._gpus = detect_gpus()

        if not self._gpus:
            info_row = Adw.ActionRow(
                title="No discrete GPUs detected",
                subtitle="GPU override is not available on this system",
            )
            group.add(info_row)
            self._gpu_row = None
            return

        options = ["System Default"] + [f"GPU {g.index} — {g.name}" for g in self._gpus]
        self._gpu_row = Adw.ComboRow(title="GPU Override")
        self._gpu_row.set_model(Gtk.StringList.new(options))

        if cfg.gpu_index is not None and cfg.gpu_index < len(self._gpus):
            self._gpu_row.set_selected(cfg.gpu_index + 1)  # +1 for "System Default"
        else:
            self._gpu_row.set_selected(0)

        group.add(self._gpu_row)

    def _build_gamescope_group(self, prefs: Adw.PreferencesPage, cfg: AppConfig) -> None:
        group = Adw.PreferencesGroup(
            title="Gamescope",
            description="Compositor wrapper for HDR, FSR/NIS upscaling, and frame cap",
        )
        prefs.add(group)

        gs = cfg.gamescope
        gs_available = shutil.which("gamescope") is not None

        self._gs_enabled_row = Adw.SwitchRow(
            title="Enable gamescope",
            subtitle="Wrap the game in a nested compositor"
            if gs_available
            else "gamescope not installed on PATH",
        )
        self._gs_enabled_row.set_active(gs.enabled and gs_available)
        self._gs_enabled_row.set_sensitive(gs_available)
        group.add(self._gs_enabled_row)

        self._gs_output_w_row = Adw.EntryRow(title="Output width (-W)")
        self._gs_output_w_row.set_text(str(gs.output_width) if gs.output_width else "")
        self._gs_output_w_row.set_tooltip_text("0 or blank = use native resolution")
        group.add(self._gs_output_w_row)

        self._gs_output_h_row = Adw.EntryRow(title="Output height (-H)")
        self._gs_output_h_row.set_text(str(gs.output_height) if gs.output_height else "")
        group.add(self._gs_output_h_row)

        self._gs_game_w_row = Adw.EntryRow(title="Internal render width (-w)")
        self._gs_game_w_row.set_text(str(gs.game_width) if gs.game_width else "")
        self._gs_game_w_row.set_tooltip_text("0 or blank = match output resolution")
        group.add(self._gs_game_w_row)

        self._gs_game_h_row = Adw.EntryRow(title="Internal render height (-h)")
        self._gs_game_h_row.set_text(str(gs.game_height) if gs.game_height else "")
        group.add(self._gs_game_h_row)

        self._gs_fullscreen_row = Adw.SwitchRow(title="Fullscreen (-f)")
        self._gs_fullscreen_row.set_active(gs.fullscreen)
        group.add(self._gs_fullscreen_row)

        self._gs_filter_options = ["none", "fsr", "nis", "linear", "integer"]
        self._gs_filter_row = Adw.ComboRow(title="Upscale filter (-F)")
        self._gs_filter_row.set_model(Gtk.StringList.new(self._gs_filter_options))
        current_filter = gs.upscale_filter or "none"
        try:
            self._gs_filter_row.set_selected(self._gs_filter_options.index(current_filter))
        except ValueError:
            self._gs_filter_row.set_selected(0)
        group.add(self._gs_filter_row)

        self._gs_sharpness_row = Adw.EntryRow(title="Sharpness (0-20)")
        self._gs_sharpness_row.set_text(str(gs.upscale_sharpness) if gs.upscale_sharpness else "")
        group.add(self._gs_sharpness_row)

        self._gs_hdr_row = Adw.SwitchRow(
            title="HDR",
            subtitle="Requires an HDR-capable gamescope build",
        )
        self._gs_hdr_row.set_active(gs.hdr)
        group.add(self._gs_hdr_row)

        self._gs_frame_limit_row = Adw.EntryRow(title="FPS cap (-r)")
        self._gs_frame_limit_row.set_text(str(gs.frame_limit) if gs.frame_limit else "")
        self._gs_frame_limit_row.set_tooltip_text("0 or blank = no cap")
        group.add(self._gs_frame_limit_row)

        self._gs_mangoapp_row = Adw.SwitchRow(
            title="MangoHud overlay (--mangoapp)",
            subtitle="Render MangoHud inside gamescope (disables outer MangoHud wrapper)",
        )
        self._gs_mangoapp_row.set_active(gs.mangoapp)
        group.add(self._gs_mangoapp_row)

        self._gs_extra_args_row = Adw.EntryRow(title="Extra args")
        self._gs_extra_args_row.set_text(gs.extra_args)
        self._gs_extra_args_row.set_tooltip_text("Passed through to gamescope unchanged")
        group.add(self._gs_extra_args_row)

    def _build_saves_group(self, prefs: Adw.PreferencesPage, cfg: AppConfig) -> None:
        group = Adw.PreferencesGroup(
            title="Saves",
            description="Absolute path to the save files directory or file for this game",
        )
        prefs.add(group)

        self._save_path_row = Adw.EntryRow(title="Save Files Path")
        self._save_path_row.set_text(cfg.save_path or "")

        detect_btn = Gtk.Button(icon_name="system-search-symbolic")
        detect_btn.add_css_class("flat")
        detect_btn.set_valign(Gtk.Align.CENTER)
        detect_btn.set_tooltip_text("Auto-detect save file locations")
        detect_btn.connect("clicked", self._on_detect_save_path)
        self._save_path_row.add_suffix(detect_btn)

        browse_btn = Gtk.Button(icon_name="document-open-symbolic")
        browse_btn.add_css_class("flat")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.connect("clicked", self._on_browse_save_path)
        self._save_path_row.add_suffix(browse_btn)

        group.add(self._save_path_row)

    def _build_hooks_group(self, prefs: Adw.PreferencesPage, cfg: AppConfig) -> None:
        from exwin.backend.hooks import _governor_tool_available, _running_in_kde

        group = Adw.PreferencesGroup(
            title="Hooks",
            description="Run toggles and shell commands before/after the game",
        )
        prefs.add(group)

        hk = cfg.hooks

        # Mount ISO
        self._hk_iso_row = Adw.EntryRow(title="Mount disc image")
        self._hk_iso_row.set_text(hk.mount_iso)
        self._hk_iso_row.set_tooltip_text(
            "Mounts the ISO via udisksctl before launch. The mount point is "
            "exported as $EXWIN_ISO_MOUNT. Unmounted automatically on exit."
        )
        browse_iso = Gtk.Button(icon_name="document-open-symbolic")
        browse_iso.add_css_class("flat")
        browse_iso.set_valign(Gtk.Align.CENTER)
        browse_iso.connect("clicked", self._on_browse_iso)
        self._hk_iso_row.add_suffix(browse_iso)
        group.add(self._hk_iso_row)

        # Kill processes
        self._hk_kill_row = Adw.EntryRow(title="Kill processes before launch")
        self._hk_kill_row.set_text(", ".join(hk.kill_processes))
        self._hk_kill_row.set_tooltip_text(
            "Comma-separated process names (pkill -x). Example: discord, steam, obs"
        )
        group.add(self._hk_kill_row)

        # KDE compositor
        self._hk_compositor_row = Adw.SwitchRow(
            title="Suspend KDE compositor",
            subtitle="Disable compositing while the game runs (KDE only)",
        )
        self._hk_compositor_row.set_active(hk.suspend_kde_compositor)
        if not _running_in_kde():
            self._hk_compositor_row.set_sensitive(False)
            self._hk_compositor_row.set_subtitle("Not running KDE — no-op")
        group.add(self._hk_compositor_row)

        # CPU governor
        self._hk_governor_row = Adw.SwitchRow(
            title="CPU performance governor",
            subtitle="Switch to 'performance' via powerprofilesctl; restore on exit",
        )
        self._hk_governor_row.set_active(hk.cpu_performance_governor)
        if _governor_tool_available() is None:
            self._hk_governor_row.set_sensitive(False)
            self._hk_governor_row.set_subtitle("No user-level governor tool found")
        group.add(self._hk_governor_row)

        # Advanced: shell escape hatch inside an expander row
        self._hk_advanced_row = Adw.ExpanderRow(
            title="Advanced — custom shell",
            subtitle="Runs under /bin/sh as your user. No sandbox.",
        )
        group.add(self._hk_advanced_row)

        # Pre-launch shell
        pre_row = Adw.ActionRow()
        pre_scroll = Gtk.ScrolledWindow()
        pre_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        pre_scroll.set_size_request(-1, 80)
        self._hk_pre_view = Gtk.TextView(
            monospace=True, top_margin=8, bottom_margin=8, left_margin=8, right_margin=8
        )
        self._hk_pre_view.add_css_class("card")
        self._hk_pre_view.get_buffer().set_text(hk.pre_launch_cmd)
        self._hk_pre_view.set_tooltip_text(
            "Runs after toggles. $EXWIN_ISO_MOUNT is set if an ISO was mounted. "
            "Non-zero exit aborts the launch."
        )
        pre_scroll.set_child(self._hk_pre_view)
        pre_row.set_child(pre_scroll)
        pre_label = Adw.ActionRow(title="Pre-launch shell")
        self._hk_advanced_row.add_row(pre_label)
        self._hk_advanced_row.add_row(pre_row)

        # Post-launch shell
        post_row = Adw.ActionRow()
        post_scroll = Gtk.ScrolledWindow()
        post_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        post_scroll.set_size_request(-1, 80)
        self._hk_post_view = Gtk.TextView(
            monospace=True, top_margin=8, bottom_margin=8, left_margin=8, right_margin=8
        )
        self._hk_post_view.add_css_class("card")
        self._hk_post_view.get_buffer().set_text(hk.post_launch_cmd)
        post_scroll.set_child(self._hk_post_view)
        post_row.set_child(post_scroll)
        post_label = Adw.ActionRow(title="Post-launch shell")
        self._hk_advanced_row.add_row(post_label)
        self._hk_advanced_row.add_row(post_row)

        self._hk_post_on_crash_row = Adw.SwitchRow(
            title="Run post-launch shell only on crash",
            subtitle="Skip post-launch when the game exits cleanly (rc=0)",
        )
        self._hk_post_on_crash_row.set_active(hk.post_launch_on_crash_only)
        self._hk_advanced_row.add_row(self._hk_post_on_crash_row)

        # Expand automatically if any advanced field is non-empty
        if hk.pre_launch_cmd or hk.post_launch_cmd or hk.post_launch_on_crash_only:
            self._hk_advanced_row.set_expanded(True)

    def _on_browse_iso(self, _btn: Gtk.Button) -> None:
        from gi.repository import Gio

        f = Gtk.FileFilter()
        f.set_name("Disc images (*.iso *.cue *.bin *.img)")
        for pat in ("*.iso", "*.cue", "*.bin", "*.img"):
            f.add_pattern(pat)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)

        dialog = Gtk.FileDialog(title="Select disc image", filters=filters)
        dialog.open(self.get_root(), None, self._on_iso_chosen)

    def _on_iso_chosen(self, dialog: Gtk.FileDialog, result) -> None:
        from gi.repository import GLib as _GLib

        try:
            gfile = dialog.open_finish(result)
        except _GLib.Error:
            return
        self._hk_iso_row.set_text(gfile.get_path())

    def _build_cover_art_group(self, prefs: Adw.PreferencesPage, app: AppEntry) -> None:
        group = Adw.PreferencesGroup(
            title="Cover Art",
            description="Local file path, image URL, or base64 data URI (data:image/…;base64,…). Leave blank to keep existing art.",
        )
        prefs.add(group)

        self._cover_row = Adw.EntryRow(title="Local path or URL")
        self._cover_row.set_text(str(app.cover_art_path) if app.cover_art_path else "")

        browse_btn = Gtk.Button(icon_name="document-open-symbolic")
        browse_btn.add_css_class("flat")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.connect("clicked", self._on_browse_cover)
        self._cover_row.add_suffix(browse_btn)

        group.add(self._cover_row)

    def _build_env_group(self, prefs: Adw.PreferencesPage, cfg: AppConfig) -> None:
        group = Adw.PreferencesGroup(
            title="Environment Variables",
            description="One KEY=VALUE per line",
        )
        prefs.add(group)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(-1, 100)

        self._env_view = Gtk.TextView(
            monospace=True, top_margin=8, bottom_margin=8, left_margin=8, right_margin=8
        )
        self._env_view.add_css_class("card")
        env_text = "\n".join(f"{k}={v}" for k, v in cfg.env.items())
        self._env_view.get_buffer().set_text(env_text)
        scroll.set_child(self._env_view)

        row = Adw.ActionRow()
        row.set_child(scroll)
        group.add(row)

    def _build_dll_group(self, prefs: Adw.PreferencesPage, cfg: AppConfig) -> None:
        group = Adw.PreferencesGroup(
            title="DLL Overrides",
            description="One DLL_NAME=override_type per line, e.g.: d3d11=n,b",
        )
        prefs.add(group)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(-1, 80)

        self._dll_view = Gtk.TextView(
            monospace=True, top_margin=8, bottom_margin=8, left_margin=8, right_margin=8
        )
        self._dll_view.add_css_class("card")
        dll_text = "\n".join(f"{k}={v}" for k, v in cfg.dll_overrides.items())
        self._dll_view.get_buffer().set_text(dll_text)
        scroll.set_child(self._dll_view)

        row = Adw.ActionRow()
        row.set_child(scroll)
        group.add(row)

    def _build_action_row(self, toolbar_view: Adw.ToolbarView) -> None:
        bar = Gtk.ActionBar()
        toolbar_view.add_bottom_bar(bar)

        if winetricks_available():
            self._apply_wt_btn = Gtk.Button(label="Apply Winetricks Now")
            self._apply_wt_btn.add_css_class("flat")
            self._apply_wt_btn.connect("clicked", self._on_apply_winetricks)
            bar.pack_start(self._apply_wt_btn)

        self._upgrade_btn = Gtk.Button(label="Upgrade Prefix")
        self._upgrade_btn.add_css_class("flat")
        self._upgrade_btn.set_tooltip_text(
            "Run `wineboot -u` to refresh system DLLs inside the existing "
            "prefix. Keeps user data; use this after switching to a newer "
            "Proton/Wine runtime."
        )
        self._upgrade_btn.connect("clicked", self._on_upgrade_prefix)
        bar.pack_start(self._upgrade_btn)

        self._rebuild_btn = Gtk.Button(label="Rebuild Prefix")
        self._rebuild_btn.add_css_class("flat")
        self._rebuild_btn.set_tooltip_text(
            "Delete and recreate the Wine prefix from scratch. "
            "Installed winetricks verbs and DLLs will be lost."
        )
        self._rebuild_btn.connect("clicked", self._on_rebuild_prefix)
        bar.pack_start(self._rebuild_btn)

        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        save_btn.add_css_class("pill")
        save_btn.connect("clicked", self._on_save)
        bar.pack_end(save_btn)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_browse_exe(self, _btn: Gtk.Button) -> None:
        from gi.repository import Gio

        f = Gtk.FileFilter()
        f.set_name("Windows Executables (*.exe)")
        f.add_pattern("*.exe")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)

        dialog = Gtk.FileDialog(title="Select Executable", filters=filters)
        # Start browsing from the install directory if it exists
        start = self._app.install_path if self._app.install_path else Path.home()
        if start.exists():
            from gi.repository import Gio as _Gio

            dialog.set_initial_folder(_Gio.File.new_for_path(str(start)))

        dialog.open(self.get_root(), None, self._on_exe_chosen)

    def _on_exe_chosen(self, dialog: Gtk.FileDialog, result) -> None:
        from gi.repository import GLib as _GLib

        try:
            gfile = dialog.open_finish(result)
        except _GLib.Error:
            return

        chosen = Path(gfile.get_path())
        install = self._app.install_path
        if install:
            try:
                rel = chosen.relative_to(install)
                self._exe_row.set_text(str(rel))
                return
            except ValueError:
                pass
        self._exe_row.set_text(str(chosen))

    def _on_save(self, _btn: Gtk.Button) -> None:
        errors = self._validate()
        if errors:
            root = self.get_root()
            if hasattr(root, "show_toast"):
                root.show_toast(errors[0])
            return

        cfg = self._read_config()
        save_app_config(self._app.app_id, self._config, cfg)

        # Persist exe_path change to DB
        new_exe = self._exe_row.get_text().strip()
        if new_exe != (self._app.exe_path or ""):
            from exwin.db.schema import get_conn

            with get_conn() as conn:
                conn.execute(
                    "UPDATE apps SET exe_path = ? WHERE id = ?",
                    (new_exe, self._app.app_id),
                )

        # Persist runtime selection to DB
        if self._runtime_row is not None and self._runtimes:
            from exwin.db.apps import update_runtime

            selected_rt = self._runtimes[self._runtime_row.get_selected()]
            update_runtime(self._app.app_id, selected_rt.db_id)

        cover_source = self._cover_row.get_text().strip()
        current_cover = str(self._app.cover_art_path) if self._app.cover_art_path else ""
        if cover_source and cover_source != current_cover:
            self._cover_row.remove_css_class("error")
            _btn.set_sensitive(False)
            _btn.set_label("Saving…")
            threading.Thread(
                target=self._cover_art_thread,
                args=(cfg, cover_source, _btn),
                daemon=True,
            ).start()
            return  # dialog closed by _finish_save or _on_cover_error

        self._on_saved(cfg)
        self.close()

    def _on_browse_cover(self, _btn: Gtk.Button) -> None:
        from gi.repository import Gio

        f = Gtk.FileFilter()
        f.set_name("Images (*.jpg *.jpeg *.png *.webp)")
        for pat in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            f.add_pattern(pat)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)

        dialog = Gtk.FileDialog(title="Select Cover Art", filters=filters)
        dialog.open(self.get_root(), None, self._on_cover_chosen)

    def _on_cover_chosen(self, dialog: Gtk.FileDialog, result) -> None:
        from gi.repository import GLib as _GLib

        try:
            gfile = dialog.open_finish(result)
        except _GLib.Error:
            return
        self._cover_row.set_text(gfile.get_path())

    def _on_detect_save_path(self, _btn: Gtk.Button) -> None:
        from exwin.backend.save_detect import detect_save_paths

        paths = detect_save_paths(self._app)
        if not paths:
            root = self.get_root()
            if hasattr(root, "show_toast"):
                root.show_toast("No save file locations detected")
            return

        dialog = Adw.AlertDialog(heading="Detected Save Locations")
        dialog.add_response("cancel", "Cancel")
        dialog.set_default_response("cancel")

        # Use a preferences group as extra child to list paths
        group = Adw.PreferencesGroup()
        self._detect_checks: list[tuple[Gtk.CheckButton, Path]] = []
        first_check: Gtk.CheckButton | None = None
        for p in paths:
            check = Gtk.CheckButton(label=str(p))
            check.set_margin_top(4)
            check.set_margin_bottom(4)
            if first_check is None:
                first_check = check
                check.set_active(True)
            else:
                check.set_group(first_check)
            row = Adw.ActionRow(title=str(p))
            row.add_prefix(check)
            row.set_activatable_widget(check)
            group.add(row)
            self._detect_checks.append((check, p))

        dialog.set_extra_child(group)
        dialog.add_response("select", "Select")
        dialog.set_response_appearance("select", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_detect_response)
        dialog.present(self)

    def _on_detect_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response != "select":
            return
        for check, path in self._detect_checks:
            if check.get_active():
                self._save_path_row.set_text(str(path))
                break

    def _on_browse_save_path(self, _btn: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Select Save Files Folder")
        dialog.select_folder(self.get_root(), None, self._on_save_path_chosen)

    def _on_save_path_chosen(self, dialog: Gtk.FileDialog, result) -> None:
        from gi.repository import GLib as _GLib

        try:
            gfile = dialog.select_folder_finish(result)
        except _GLib.Error:
            return
        self._save_path_row.set_text(gfile.get_path())

    def _cover_art_thread(self, cfg: AppConfig, source: str, btn: Gtk.Button) -> None:
        try:
            apply_custom_cover_art(self._app.app_id, source, self._config)
        except Exception as exc:
            GLib.idle_add(self._on_cover_error, str(exc), btn)
            return
        GLib.idle_add(self._finish_save, cfg)

    def _finish_save(self, cfg: AppConfig) -> None:
        self._on_saved(cfg)
        self.close()

    def _on_cover_error(self, message: str, btn: Gtk.Button) -> None:
        btn.set_sensitive(True)
        btn.set_label("Save")
        self._cover_row.add_css_class("error")
        root = self.get_root()
        if hasattr(root, "show_toast"):
            root.show_toast(f"Cover art error: {message}")

    def _on_apply_winetricks(self, _btn: Gtk.Button) -> None:
        verbs_text = self._winetricks_row.get_text().strip()
        verbs = verbs_text.split() if verbs_text else []
        if not verbs:
            return

        self._apply_wt_btn.set_sensitive(False)
        self._apply_wt_btn.set_label("Applying…")

        p_root = self._app.prefix_path
        threading.Thread(
            target=self._winetricks_thread,
            args=(p_root, verbs),
            daemon=True,
        ).start()

    def _winetricks_thread(self, p_root: Path, verbs: list[str]) -> None:
        log_path = self._config.logs_dir / f"{self._app.app_id}-winetricks.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w") as log_file:
                proc = run_verbs(
                    p_root,
                    verbs,
                    self._runtime,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
                proc.wait()
            ok = proc.returncode == 0
        except Exception as exc:
            try:
                log_path.write_text(f"winetricks invocation raised: {exc!r}\n")
            except OSError:
                pass
            ok = False
        GLib.idle_add(self._on_winetricks_done, ok, log_path)

    def _on_winetricks_done(self, success: bool, log_path: Path) -> None:
        self._apply_wt_btn.set_sensitive(True)
        self._apply_wt_btn.set_label("Apply Winetricks Now")
        # Show result via the parent window's toast if we can reach it
        root = self.get_root()
        if hasattr(root, "show_toast"):
            if success:
                msg = "Winetricks verbs applied."
            else:
                msg = f"Winetricks failed — see {log_path}"
            root.show_toast(msg)

    def _on_upgrade_prefix(self, _btn: Gtk.Button) -> None:
        if self._runtime is None:
            root = self.get_root()
            if hasattr(root, "show_toast"):
                root.show_toast("No runtime selected — assign one first")
            return
        self._upgrade_btn.set_sensitive(False)
        self._upgrade_btn.set_label("Upgrading…")
        threading.Thread(target=self._upgrade_thread, daemon=True).start()

    def _upgrade_thread(self) -> None:
        from exwin.backend.prefix_tools import upgrade_prefix

        err: str | None = None
        rc: int | None = None
        log_path = self._config.logs_dir / f"{self._app.app_id}-wineboot-u.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w") as log_file:
                proc = upgrade_prefix(
                    self._app.prefix_path,
                    self._runtime,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
                # wineboot -u normally finishes well under two minutes; guard
                # against the prefix getting stuck bootstrapping.
                try:
                    rc = proc.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    err = "wineboot -u timed out after 3 minutes"
        except Exception as exc:
            err = str(exc)
        GLib.idle_add(self._on_upgrade_done, err, rc, log_path)

    def _on_upgrade_done(self, err: str | None, rc: int | None, log_path: Path) -> None:
        self._upgrade_btn.set_sensitive(True)
        self._upgrade_btn.set_label("Upgrade Prefix")
        root = self.get_root()
        if not hasattr(root, "show_toast"):
            return
        if err:
            root.show_toast(f"Prefix upgrade failed: {err}")
        elif rc and rc != 0:
            root.show_toast(f"wineboot -u exited with rc={rc}; see {log_path}")
        else:
            root.show_toast("Prefix upgraded")

    def _on_rebuild_prefix(self, _btn: Gtk.Button) -> None:
        if self._runtime is None:
            root = self.get_root()
            if hasattr(root, "show_toast"):
                root.show_toast("No runtime selected — assign one first")
            return

        dialog = Adw.AlertDialog(
            heading="Rebuild Wine Prefix?",
            body=(
                "This deletes and recreates the Wine prefix from scratch. "
                "Any winetricks verbs, DLL overrides, or other state inside "
                "the prefix will be lost. Game files and save files stored "
                "outside the prefix are unaffected."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("rebuild", "Rebuild")
        dialog.set_response_appearance("rebuild", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_rebuild_confirmed)
        dialog.present(self)

    def _on_rebuild_confirmed(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response != "rebuild":
            return
        self._rebuild_btn.set_sensitive(False)
        self._rebuild_btn.set_label("Rebuilding…")
        threading.Thread(target=self._rebuild_thread, daemon=True).start()

    def _rebuild_thread(self) -> None:
        from exwin.backend.prefix import rebuild_prefix

        err: str | None = None
        try:
            rebuild_prefix(self._app.app_id, self._config, self._runtime, self._app_config.arch)
        except Exception as exc:
            err = str(exc)
        GLib.idle_add(self._on_rebuild_done, err)

    def _on_rebuild_done(self, err: str | None) -> None:
        self._rebuild_btn.set_sensitive(True)
        self._rebuild_btn.set_label("Rebuild Prefix")
        root = self.get_root()
        if hasattr(root, "show_toast"):
            if err:
                root.show_toast(f"Prefix rebuild failed: {err}")
            else:
                root.show_toast("Prefix rebuilt")

    def _snapshot(self) -> dict:
        """Capture current field values for dirty comparison."""
        env_buf = self._env_view.get_buffer()
        dll_buf = self._dll_view.get_buffer()
        pre_buf = self._hk_pre_view.get_buffer()
        post_buf = self._hk_post_view.get_buffer()
        return {
            "exe": self._exe_row.get_text(),
            "arch": self._arch_row.get_selected(),
            "dxvk": self._dxvk_row.get_active(),
            "vkd3d": self._vkd3d_row.get_active(),
            "winetricks": self._winetricks_row.get_text(),
            "gamemode": self._gamemode_row.get_active(),
            "mangohud": self._mangohud_row.get_active(),
            "args": self._args_row.get_text(),
            "save_path": self._save_path_row.get_text(),
            "cover": self._cover_row.get_text(),
            "env": env_buf.get_text(env_buf.get_start_iter(), env_buf.get_end_iter(), False),
            "dll": dll_buf.get_text(dll_buf.get_start_iter(), dll_buf.get_end_iter(), False),
            "runtime": self._runtime_row.get_selected() if self._runtime_row else 0,
            "gpu": self._gpu_row.get_selected() if self._gpu_row else 0,
            "hk_iso": self._hk_iso_row.get_text(),
            "hk_kill": self._hk_kill_row.get_text(),
            "hk_compositor": self._hk_compositor_row.get_active(),
            "hk_governor": self._hk_governor_row.get_active(),
            "hk_pre": pre_buf.get_text(pre_buf.get_start_iter(), pre_buf.get_end_iter(), False),
            "hk_post": post_buf.get_text(post_buf.get_start_iter(), post_buf.get_end_iter(), False),
            "hk_post_on_crash": self._hk_post_on_crash_row.get_active(),
            "umu": self._umu_row.get_selected(),
        }

    def _is_dirty(self) -> bool:
        return self._snapshot() != self._initial_state

    def _on_close_attempt(self, _dialog: Adw.Dialog) -> None:
        if not self._is_dirty():
            self.force_close()
            return
        confirm = Adw.AlertDialog(heading="Unsaved Changes", body="Discard changes?")
        confirm.add_response("cancel", "Keep Editing")
        confirm.add_response("discard", "Discard")
        confirm.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        confirm.set_default_response("cancel")
        confirm.connect("response", self._on_discard_response)
        confirm.present(self)

    def _on_discard_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response == "discard":
            self.force_close()

    def _validate(self) -> list[str]:
        """Validate text fields; return a list of error messages (empty = valid)."""
        errors: list[str] = []

        # Env vars: each non-empty, non-comment line must contain '='
        env_buf = self._env_view.get_buffer()
        env_text = env_buf.get_text(env_buf.get_start_iter(), env_buf.get_end_iter(), False)
        for i, line in enumerate(env_text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                errors.append(f"Env var line {i}: missing '=' (expected KEY=VALUE)")
                break

        # DLL overrides: each non-empty line must contain '='
        dll_buf = self._dll_view.get_buffer()
        dll_text = dll_buf.get_text(dll_buf.get_start_iter(), dll_buf.get_end_iter(), False)
        for i, line in enumerate(dll_text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                errors.append(f"DLL override line {i}: missing '=' (expected DLL_NAME=type)")
                break

        # Winetricks verbs: no special characters
        verbs_text = self._winetricks_row.get_text().strip()
        if verbs_text:
            import re

            for verb in verbs_text.split():
                if not re.match(r"^[a-zA-Z0-9_\-]+$", verb):
                    errors.append(f"Invalid winetricks verb: '{verb}'")
                    break

        return errors

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_config(self) -> AppConfig:
        verbs_text = self._winetricks_row.get_text().strip()
        verbs = verbs_text.split() if verbs_text else []

        args_text = self._args_row.get_text().strip()
        launch_args = args_text.split() if args_text else []

        env = _parse_kv_text(self._env_view.get_buffer())
        dll_overrides = _parse_kv_text(self._dll_view.get_buffer())

        gpu_index = None
        if self._gpu_row is not None:
            gpu_sel = self._gpu_row.get_selected()
            gpu_index = None if gpu_sel == 0 else (gpu_sel - 1)

        umu_sel = self._umu_row.get_selected()
        use_umu: bool | None = None if umu_sel == 0 else (umu_sel == 1)

        return AppConfig(
            arch=_ARCH_OPTIONS[self._arch_row.get_selected()],
            winetricks_verbs=verbs,
            dxvk=self._dxvk_row.get_active(),
            vkd3d=self._vkd3d_row.get_active(),
            env=env,
            launch_args=launch_args,
            gamemode=self._gamemode_row.get_active(),
            mangohud=self._mangohud_row.get_active(),
            dll_overrides=dll_overrides,
            gpu_index=gpu_index,
            use_umu=use_umu,
            save_path=self._save_path_row.get_text().strip(),
            gamescope=self._read_gamescope_config(),
            hooks=self._read_hook_config(),
        )

    def _read_hook_config(self) -> HookConfig:
        kill_raw = self._hk_kill_row.get_text().strip()
        kill_list = [s.strip() for s in kill_raw.split(",") if s.strip()] if kill_raw else []

        pre_buf = self._hk_pre_view.get_buffer()
        post_buf = self._hk_post_view.get_buffer()
        pre_text = pre_buf.get_text(pre_buf.get_start_iter(), pre_buf.get_end_iter(), False)
        post_text = post_buf.get_text(post_buf.get_start_iter(), post_buf.get_end_iter(), False)

        return HookConfig(
            mount_iso=self._hk_iso_row.get_text().strip(),
            kill_processes=kill_list,
            suspend_kde_compositor=self._hk_compositor_row.get_active(),
            cpu_performance_governor=self._hk_governor_row.get_active(),
            pre_launch_cmd=pre_text.strip(),
            post_launch_cmd=post_text.strip(),
            post_launch_on_crash_only=self._hk_post_on_crash_row.get_active(),
        )

    def _read_gamescope_config(self) -> GamescopeConfig:
        def _int(entry: Adw.EntryRow) -> int:
            text = entry.get_text().strip()
            try:
                return int(text) if text else 0
            except ValueError:
                return 0

        filter_idx = self._gs_filter_row.get_selected()
        filter_name = self._gs_filter_options[filter_idx]
        return GamescopeConfig(
            enabled=self._gs_enabled_row.get_active(),
            output_width=_int(self._gs_output_w_row),
            output_height=_int(self._gs_output_h_row),
            game_width=_int(self._gs_game_w_row),
            game_height=_int(self._gs_game_h_row),
            fullscreen=self._gs_fullscreen_row.get_active(),
            upscale_filter="" if filter_name == "none" else filter_name,
            upscale_sharpness=_int(self._gs_sharpness_row),
            hdr=self._gs_hdr_row.get_active(),
            frame_limit=_int(self._gs_frame_limit_row),
            mangoapp=self._gs_mangoapp_row.get_active(),
            extra_args=self._gs_extra_args_row.get_text().strip(),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_kv_text(buf: Gtk.TextBuffer) -> dict[str, str]:
    """Parse a multi-line KEY=VALUE TextBuffer into a dict, ignoring blank/comment lines."""
    text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result
