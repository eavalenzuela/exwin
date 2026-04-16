"""Dialog for adding an already-installed game to the library.

Walks the user through a minimal form, then creates/initialises the Wine prefix,
applies any requested winetricks verbs, optionally installs DXVK/VKD3D, saves
an app.toml, and inserts the entry into the library DB.  All the heavy work
runs in a background thread so the UI stays responsive.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from exwin.backend.app_config import AppConfig, save_app_config  # noqa: E402
from exwin.backend.config import Config  # noqa: E402
from exwin.backend.dxvk import install_dxvk, install_vkd3d  # noqa: E402
from exwin.backend.prefix import create_prefix  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402
from exwin.backend.winetricks import is_available as winetricks_available  # noqa: E402
from exwin.backend.winetricks import run_verbs  # noqa: E402
from exwin.models import AppEntry, AppSource  # noqa: E402
from exwin.ui.winetricks_picker import WinetricksRow  # noqa: E402

_ARCH_OPTIONS = ["win64", "win32"]


def _slugify(name: str) -> str:
    """Create a url-safe slug from a game name."""
    slug = name.lower().strip()
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug)
    # Collapse multiple dashes and strip leading/trailing
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "game"


class AddExistingDialog(Adw.Dialog):
    """Register an already-installed game and set up its Wine prefix."""

    def __init__(
        self,
        config: Config,
        runtimes: list[Runtime],
        on_added: Callable[[AppEntry], None],
        **kwargs,
    ) -> None:
        super().__init__(title="Add Existing Game", content_width=500, content_height=560, **kwargs)
        self._config = config
        self._runtimes = runtimes
        self._on_added = on_added

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        self._header = Adw.HeaderBar()
        toolbar_view.add_top_bar(self._header)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        toolbar_view.set_content(self._stack)

        self._build_form_page()
        self._build_installing_page()
        self._build_done_page()
        self._build_error_page()

        self._stack.set_visible_child_name("form")

    # ------------------------------------------------------------------
    # Page builders
    # ------------------------------------------------------------------

    def _build_form_page(self) -> None:
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        page = Adw.PreferencesPage()
        scroll.set_child(page)

        # ── Game info group ─────────────────────────────────────────────
        info_group = Adw.PreferencesGroup(title="Game Info")
        page.add(info_group)

        self._name_row = Adw.EntryRow(title="Name")
        info_group.add(self._name_row)

        # ── Paths group ─────────────────────────────────────────────────
        paths_group = Adw.PreferencesGroup(title="Paths")
        page.add(paths_group)

        self._install_row = Adw.EntryRow(title="Install Directory")
        install_browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        install_browse.add_css_class("flat")
        install_browse.connect("clicked", self._on_browse_install)
        self._install_row.add_suffix(install_browse)
        paths_group.add(self._install_row)

        self._exe_row = Adw.EntryRow(title="Executable (relative to install dir)")
        exe_browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        exe_browse.add_css_class("flat")
        exe_browse.connect("clicked", self._on_browse_exe)
        self._exe_row.add_suffix(exe_browse)
        paths_group.add(self._exe_row)

        self._prefix_row = Adw.EntryRow(title="Wine Prefix (optional)")
        prefix_browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        prefix_browse.add_css_class("flat")
        prefix_browse.connect("clicked", self._on_browse_prefix)
        self._prefix_row.add_suffix(prefix_browse)
        paths_group.add(self._prefix_row)

        # ── Wine setup group ────────────────────────────────────────────
        wine_group = Adw.PreferencesGroup(
            title="Wine Setup",
            description="Configure the prefix so the game will actually run.",
        )
        page.add(wine_group)

        runtime_model = Gtk.StringList()
        if self._runtimes:
            for rt in self._runtimes:
                runtime_model.append(rt.name)
        else:
            runtime_model.append("None detected")
        self._runtime_row = Adw.ComboRow(title="Wine/Proton Runtime", model=runtime_model)
        self._runtime_row.set_selected(0)
        wine_group.add(self._runtime_row)

        self._arch_row = Adw.ComboRow(title="Windows Architecture")
        self._arch_row.set_model(Gtk.StringList.new(_ARCH_OPTIONS))
        self._arch_row.set_selected(0)
        wine_group.add(self._arch_row)

        self._winetricks_row = WinetricksRow(title="Winetricks Verbs", parent=self)
        self._winetricks_row.set_tooltip_text(
            "Pick verbs to apply (e.g. vcrun2019, corefonts, d3dx9)"
        )
        if not winetricks_available():
            self._winetricks_row.set_sensitive(False)
            self._winetricks_row.set_title("Winetricks Verbs (winetricks not installed)")
        wine_group.add(self._winetricks_row)

        self._dxvk_row = Adw.SwitchRow(title="Install DXVK", subtitle="DirectX 9/10/11 → Vulkan")
        wine_group.add(self._dxvk_row)

        self._vkd3d_row = Adw.SwitchRow(
            title="Install VKD3D-Proton", subtitle="DirectX 12 → Vulkan"
        )
        wine_group.add(self._vkd3d_row)

        # ── Add button (bottom bar) ─────────────────────────────────────
        add_btn = Gtk.Button(label="Add to Library")
        add_btn.add_css_class("suggested-action")
        add_btn.add_css_class("pill")
        add_btn.set_halign(Gtk.Align.CENTER)
        add_btn.set_margin_top(8)
        add_btn.set_margin_bottom(8)
        add_btn.connect("clicked", self._on_add_clicked)
        self._add_btn = add_btn

        btn_box = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=8, margin_bottom=8)
        btn_box.append(add_btn)

        # Wrap scroll + bottom bar in a box so the form page owns its button
        form_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        form_box.append(scroll)
        form_box.append(btn_box)

        self._stack.add_named(form_box, "form")

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

        self._install_status_label = Gtk.Label(label="Setting up…")
        self._install_status_label.add_css_class("heading")
        status_box.append(self._install_status_label)
        box.append(status_box)

        log_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        log_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._log_buffer = Gtk.TextBuffer()
        log_view = Gtk.TextView(buffer=self._log_buffer, editable=False, monospace=True)
        log_view.add_css_class("caption")
        log_scroll.set_child(log_view)
        self._log_scroll = log_scroll
        box.append(log_scroll)

        self._stack.add_named(box, "installing")

    def _build_done_page(self) -> None:
        page = Adw.StatusPage(title="Added!", icon_name="emblem-ok-symbolic")
        close_btn = Gtk.Button(label="Close")
        close_btn.add_css_class("pill")
        close_btn.connect("clicked", lambda _b: self.close())
        page.set_child(close_btn)
        self._done_page = page
        self._stack.add_named(page, "done")

    def _build_error_page(self) -> None:
        page = Adw.StatusPage(title="Setup Failed", icon_name="dialog-error-symbolic")
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER
        )
        back_btn = Gtk.Button(label="Back")
        back_btn.add_css_class("pill")
        back_btn.connect("clicked", lambda _b: self._stack.set_visible_child_name("form"))
        close_btn = Gtk.Button(label="Close")
        close_btn.add_css_class("destructive-action")
        close_btn.add_css_class("pill")
        close_btn.connect("clicked", lambda _b: self.close())
        btn_box.append(back_btn)
        btn_box.append(close_btn)
        page.set_child(btn_box)
        self._error_page = page
        self._stack.add_named(page, "error")

    # ------------------------------------------------------------------
    # Browse handlers
    # ------------------------------------------------------------------

    def _on_browse_install(self, _btn: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Select Install Directory")
        dialog.select_folder(self.get_root(), None, self._on_install_selected)

    def _on_install_selected(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self._install_row.set_text(folder.get_path())
        except Exception:
            pass

    def _on_browse_exe(self, _btn: Gtk.Button) -> None:
        install_dir = self._install_row.get_text().strip()
        dialog = Gtk.FileDialog(title="Select Executable")
        if install_dir and Path(install_dir).is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(install_dir))
        dialog.open(self.get_root(), None, self._on_exe_selected)

    def _on_exe_selected(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.open_finish(result)
            if file:
                exe_full = file.get_path()
                install_dir = self._install_row.get_text().strip()
                if install_dir and exe_full.startswith(install_dir):
                    rel = str(Path(exe_full).relative_to(install_dir))
                    self._exe_row.set_text(rel)
                else:
                    self._exe_row.set_text(exe_full)
        except Exception:
            pass

    def _on_browse_prefix(self, _btn: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Select Wine Prefix Directory")
        dialog.select_folder(self.get_root(), None, self._on_prefix_selected)

    def _on_prefix_selected(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self._prefix_row.set_text(folder.get_path())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Add handler
    # ------------------------------------------------------------------

    def _on_add_clicked(self, _btn: Gtk.Button) -> None:
        name = self._name_row.get_text().strip()
        install_path = self._install_row.get_text().strip()
        exe_path = self._exe_row.get_text().strip()
        prefix_path = self._prefix_row.get_text().strip()

        # Validation
        if not name:
            self._show_toast("Please enter a game name")
            return
        if not install_path or not Path(install_path).is_dir():
            self._show_toast("Please select a valid install directory")
            return
        if not exe_path:
            self._show_toast("Please specify an executable")
            return

        install_dir = Path(install_path)
        full_exe = install_dir / exe_path
        if not full_exe.exists():
            self._show_toast(f"Executable not found: {full_exe}")
            return

        # Runtime required — we need it to init the prefix and launch the game
        if not self._runtimes:
            self._show_toast("No Wine/Proton runtime available — configure one in Settings first")
            return
        rt_idx = self._runtime_row.get_selected()
        runtime = (
            self._runtimes[rt_idx]
            if rt_idx != Gtk.INVALID_LIST_POSITION and rt_idx < len(self._runtimes)
            else self._runtimes[0]
        )

        arch = _ARCH_OPTIONS[self._arch_row.get_selected()]
        verbs_text = self._winetricks_row.get_text().strip()
        verbs = verbs_text.split() if verbs_text else []
        install_dxvk_flag = self._dxvk_row.get_active()
        install_vkd3d_flag = self._vkd3d_row.get_active()

        app_id = f"manual-{_slugify(name)}"
        prefix_override = Path(prefix_path) if prefix_path else None

        # Switch to progress page
        self._stack.set_visible_child_name("installing")
        self._install_spinner.set_spinning(True)
        self._install_status_label.set_label("Setting up prefix…")
        self._log_buffer.set_text("")
        self._add_btn.set_sensitive(False)

        import threading

        threading.Thread(
            target=self._setup_thread,
            args=(
                app_id,
                name,
                install_dir,
                exe_path,
                prefix_override,
                runtime,
                arch,
                verbs,
                install_dxvk_flag,
                install_vkd3d_flag,
            ),
            daemon=True,
        ).start()

    def _setup_thread(
        self,
        app_id: str,
        name: str,
        install_dir: Path,
        exe_path: str,
        prefix_override: Path | None,
        runtime: Runtime,
        arch: str,
        verbs: list[str],
        install_dxvk_flag: bool,
        install_vkd3d_flag: bool,
    ) -> None:
        def _log(msg: str) -> None:
            GLib.idle_add(self._append_log, msg)

        try:
            # 1. Create (or reuse) the Wine prefix
            if prefix_override:
                _log(f"Using existing prefix: {prefix_override}")
                prefix_dir = prefix_override
                prefix_dir.mkdir(parents=True, exist_ok=True)
            else:
                _log("Creating Wine prefix (this may take a moment)…")
                prefix_dir = create_prefix(app_id, self._config, runtime, arch)
                _log(f"Prefix ready at {prefix_dir}")

            # 2. Winetricks verbs
            if verbs:
                if not winetricks_available():
                    _log("Warning: winetricks not found — skipping verb installation.")
                else:
                    _log(f"Applying winetricks: {' '.join(verbs)}")
                    log_path = self._config.logs_dir / f"{app_id}-winetricks.log"
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(log_path, "w") as log_file:
                        proc = run_verbs(
                            prefix_dir,
                            verbs,
                            runtime,
                            stdout=log_file,
                            stderr=subprocess.STDOUT,
                        )
                        proc.wait()
                    rc = proc.returncode
                    if rc == 0:
                        _log(f"winetricks finished (exit code 0). Log: {log_path}")
                    else:
                        _log(f"winetricks failed (exit code {rc}). Full log at: {log_path}")
                        # Tail the log into the dialog so the user can see what went wrong
                        try:
                            tail = log_path.read_text(errors="replace").splitlines()[-30:]
                            if tail:
                                _log("── winetricks output (last 30 lines) ──")
                                for line in tail:
                                    _log(line)
                                _log("──────────────────────────────────────")
                        except OSError:
                            pass

            # 3. DXVK
            if install_dxvk_flag:
                try:
                    install_dxvk(prefix_dir, runtime, on_progress=_log)
                except Exception as exc:
                    _log(f"DXVK install failed: {exc}")

            # 4. VKD3D-Proton
            if install_vkd3d_flag:
                try:
                    install_vkd3d(prefix_dir, runtime, on_progress=_log)
                except Exception as exc:
                    _log(f"vkd3d-proton install failed: {exc}")

            # 5. Save per-app config
            app_config = AppConfig(
                arch=arch,
                winetricks_verbs=verbs,
                dxvk=install_dxvk_flag,
                vkd3d=install_vkd3d_flag,
            )
            save_app_config(app_id, self._config, app_config)
            _log("Saved app.toml.")

            # 6. Insert into library DB
            from exwin.db.apps import insert_app

            app = AppEntry(
                app_id=app_id,
                name=name,
                source=AppSource.MANUAL,
                install_path=install_dir,
                prefix_path=prefix_dir,
                exe_path=exe_path,
                runtime_id=runtime.db_id,
                install_date=datetime.now(tz=UTC).isoformat(),
            )
            insert_app(app)
            _log(f'✓ "{name}" added to library.')
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))
            return

        GLib.idle_add(self._on_success, app)

    def _on_success(self, app: AppEntry) -> None:
        self._install_spinner.set_spinning(False)
        self._done_page.set_description(f'"{app.name}" is ready to launch.')
        self._stack.set_visible_child_name("done")
        self._on_added(app)

    def _on_error(self, message: str) -> None:
        self._install_spinner.set_spinning(False)
        self._add_btn.set_sensitive(True)
        self._error_page.set_description(message)
        self._stack.set_visible_child_name("error")

    def _append_log(self, line: str) -> None:
        end = self._log_buffer.get_end_iter()
        self._log_buffer.insert(end, line + "\n")
        adj = self._log_scroll.get_vadjustment()
        adj.set_value(adj.get_upper())

    def _show_toast(self, msg: str) -> None:
        root = self.get_root()
        if hasattr(root, "show_toast"):
            root.show_toast(msg)
