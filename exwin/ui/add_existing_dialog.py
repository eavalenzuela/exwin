"""Dialog for adding an already-installed game to the library."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, Gtk  # noqa: E402

from exwin.backend.config import Config  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402
from exwin.models import AppEntry  # noqa: E402


def _slugify(name: str) -> str:
    """Create a url-safe slug from a game name."""
    slug = name.lower().strip()
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug)
    # Collapse multiple dashes and strip leading/trailing
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "game"


class AddExistingDialog(Adw.Dialog):
    """Register an already-installed game without running an installer."""

    def __init__(
        self,
        config: Config,
        runtimes: list[Runtime],
        on_added: Callable[[AppEntry], None],
        **kwargs,
    ) -> None:
        super().__init__(title="Add Existing Game", content_width=480, content_height=520, **kwargs)
        self._config = config
        self._runtimes = runtimes
        self._on_added = on_added

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar_view.set_content(scroll)

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

        # Install directory
        self._install_row = Adw.EntryRow(title="Install Directory")
        install_browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        install_browse.add_css_class("flat")
        install_browse.connect("clicked", self._on_browse_install)
        self._install_row.add_suffix(install_browse)
        paths_group.add(self._install_row)

        # Executable path (relative to install dir)
        self._exe_row = Adw.EntryRow(title="Executable (relative to install dir)")
        exe_browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        exe_browse.add_css_class("flat")
        exe_browse.connect("clicked", self._on_browse_exe)
        self._exe_row.add_suffix(exe_browse)
        paths_group.add(self._exe_row)

        # Wine prefix (optional — will create one if empty)
        self._prefix_row = Adw.EntryRow(title="Wine Prefix (optional)")
        prefix_browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        prefix_browse.add_css_class("flat")
        prefix_browse.connect("clicked", self._on_browse_prefix)
        self._prefix_row.add_suffix(prefix_browse)
        paths_group.add(self._prefix_row)

        # ── Runtime group ───────────────────────────────────────────────
        runtime_group = Adw.PreferencesGroup(title="Runtime")
        page.add(runtime_group)

        runtime_model = Gtk.StringList()
        for rt in runtimes:
            runtime_model.append(rt.name)
        self._runtime_dropdown = Adw.ComboRow(title="Wine/Proton Runtime", model=runtime_model)
        runtime_group.add(self._runtime_dropdown)

        # ── Add button ──────────────────────────────────────────────────
        add_btn = Gtk.Button(label="Add to Library")
        add_btn.add_css_class("suggested-action")
        add_btn.add_css_class("pill")
        add_btn.set_halign(Gtk.Align.CENTER)
        add_btn.set_margin_top(16)
        add_btn.set_margin_bottom(16)
        add_btn.connect("clicked", self._on_add_clicked)

        btn_group = Adw.PreferencesGroup()
        page.add(btn_group)
        # Wrap button in a box to add to preferences page
        btn_box = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=8, margin_bottom=8)
        btn_box.append(add_btn)
        self._add_btn = add_btn
        # Add as suffix of an empty row to keep it in the preferences page
        toolbar_view.add_bottom_bar(btn_box)

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
                    # Make relative
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

        # Resolve exe path
        full_exe = Path(install_path) / exe_path
        if not full_exe.exists():
            self._show_toast(f"Executable not found: {full_exe}")
            return

        app_id = f"manual-{_slugify(name)}"

        # Runtime
        rt_idx = self._runtime_dropdown.get_selected()
        runtime = self._runtimes[rt_idx] if rt_idx < len(self._runtimes) else None
        runtime_id = runtime.db_id if runtime else None

        # Create prefix if not specified
        if not prefix_path:
            from exwin.backend.prefix import create_prefix

            if runtime:
                proot = create_prefix(app_id, self._config, runtime)
                prefix_path = str(proot)

        from exwin.db.apps import insert_app

        app = AppEntry(
            app_id=app_id,
            name=name,
            source="manual",
            install_path=install_path,
            prefix_path=prefix_path,
            exe_path=exe_path,
            runtime_id=runtime_id,
            install_date=datetime.now(tz=UTC).isoformat(),
        )

        try:
            insert_app(app)
        except Exception as exc:
            self._show_toast(f"Failed to add game: {exc}")
            return

        self._on_added(app)
        self.close()

    def _show_toast(self, msg: str) -> None:
        root = self.get_root()
        if hasattr(root, "show_toast"):
            root.show_toast(msg)
