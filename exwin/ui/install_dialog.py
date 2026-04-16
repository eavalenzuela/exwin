"""Multi-stage installer dialog — handles both GOG (innoextract) and generic (Wine) installers."""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from exwin.backend import redist_scanner  # noqa: E402
from exwin.backend.archive_installer import (  # noqa: E402
    archive_tool_available,
    detect_archive_type,
    finalize_archive_install,
    install_archive,
)
from exwin.backend.config import Config  # noqa: E402
from exwin.backend.generic_installer import (  # noqa: E402
    detect_installer_type,
    finalize_generic_install,
    pick_best_exe,
    run_wine_installer,
    scan_candidate_exes,
)
from exwin.backend.gog_installer import (  # noqa: E402
    app_id_from_info,
    find_rar_tool,
    find_sibling_parts,
    probe,
)
from exwin.backend.install_worker import install_gog, install_gog_dlc  # noqa: E402
from exwin.backend.redist_scanner import RedistFinding, apply_finding  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402
from exwin.db.apps import get_all_apps  # noqa: E402
from exwin.models import AppEntry, AppSource  # noqa: E402
from exwin.ui.install_pages import (  # noqa: E402
    _ARCH_OPTIONS,
    build_confirm_archive_page,
    build_confirm_generic_page,
    build_confirm_gog_page,
    build_done_page,
    build_error_page,
    build_exe_select_page,
    build_installing_page,
    build_redist_page,
    build_welcome_page,
    build_wine_running_page,
)


class InstallDialog(Adw.Dialog):
    """Walks the user through installing a GOG or generic Windows installer."""

    def __init__(
        self,
        config: Config,
        runtimes: list[Runtime],
        on_installed: Callable[[AppEntry], None],
        initial_installer: Path | None = None,
        **kwargs,
    ) -> None:
        super().__init__(title="Install Game", content_width=500, content_height=520, **kwargs)
        self._config = config
        self._runtimes = runtimes
        self._on_installed = on_installed
        self._initial_installer = initial_installer
        self._installer_path: Path | None = None
        self._installer_parts: list[Path] = []
        self._installer_type: str = "innosetup"  # "innosetup" | "generic" | "msi" | "archive"
        self._wine_proc: subprocess.Popen | None = None  # running Wine installer subprocess
        self._generic_prefix_root: Path | None = None
        self._generic_runtime: Runtime | None = None
        self._generic_arch: str = "win64"
        self._generic_dlc_mode: bool = False
        self._generic_dlc_base_app: AppEntry | None = None
        self._gog_wine_mode: bool = False  # True when GOG .exe runs interactively via Wine
        self._gog_probe_info = None  # InstallerInfo from probe()
        self._archive_install_dir: Path | None = None
        self._archive_candidates: list[Path] = []
        self._redist_app: AppEntry | None = None
        self._redist_runtime: Runtime | None = None
        self._redist_findings: list[RedistFinding] = []
        self._redist_checks: dict[str, Gtk.CheckButton] = {}
        self._last_install_runtime: Runtime | None = None

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

        self._build_pages()

        if self._initial_installer and self._initial_installer.exists():
            self._installer_path = self._initial_installer
            self._installer_parts = find_sibling_parts(self._installer_path)
            self._show_probing()
        else:
            self._stack.set_visible_child_name("welcome")
            self._set_step(1)

    # ------------------------------------------------------------------
    # Page setup (delegates to install_pages module)
    # ------------------------------------------------------------------

    def _build_pages(self) -> None:
        build_welcome_page(self._stack, self._on_choose_clicked)

        gog = build_confirm_gog_page(
            self._stack,
            self._runtimes,
            self._base_games,
            on_install_clicked=self._on_install_clicked,
            on_gog_wine_toggled=self._on_gog_wine_toggled,
            on_dlc_toggled=self._on_dlc_toggled,
        )
        self._rar_warn_banner = gog.rar_warn_banner
        self._title_row = gog.title_row
        self._gameid_row = gog.gameid_row
        self._lang_row = gog.lang_row
        self._parts_row = gog.parts_row
        self._runtime_row = gog.runtime_row
        self._arch_row = gog.arch_row
        self._winetricks_row = gog.winetricks_row
        self._dlc_switch_row = gog.dlc_switch_row
        self._base_game_row = gog.base_game_row
        self._dxvk_row = gog.dxvk_row
        self._vkd3d_row = gog.vkd3d_row
        self._gog_wine_row = gog.gog_wine_row
        self._install_btn = gog.install_btn

        generic = build_confirm_generic_page(
            self._stack,
            self._runtimes,
            self._base_games,
            on_install_clicked=self._on_generic_install_clicked,
            on_dlc_toggled=self._on_generic_dlc_toggled,
        )
        self._generic_file_row = generic.file_row
        self._generic_runtime_row = generic.runtime_row
        self._generic_arch_row = generic.arch_row
        self._generic_winetricks_row = generic.winetricks_row
        self._generic_dlc_switch_row = generic.dlc_switch_row
        self._generic_base_game_row = generic.base_game_row
        self._generic_dxvk_row = generic.dxvk_row
        self._generic_vkd3d_row = generic.vkd3d_row

        archive = build_confirm_archive_page(
            self._stack,
            self._runtimes,
            on_install_clicked=self._on_archive_install_clicked,
        )
        self._archive_file_row = archive.file_row
        self._archive_name_row = archive.name_row
        self._archive_runtime_row = archive.runtime_row
        self._archive_arch_row = archive.arch_row
        self._archive_winetricks_row = archive.winetricks_row
        self._archive_dxvk_row = archive.dxvk_row
        self._archive_vkd3d_row = archive.vkd3d_row
        self._archive_tool_warn_banner = archive.tool_warn_banner
        self._archive_install_btn = archive.install_btn

        inst = build_installing_page(self._stack)
        self._install_spinner = inst.spinner
        self._install_status_label = inst.status_label
        self._progress_bar = inst.progress_bar
        self._log_buffer = inst.log_buffer
        self._log_scroll = inst.log_scroll

        build_wine_running_page(self._stack, self._on_cancel_wine)

        exe = build_exe_select_page(
            self._stack,
            on_exe_confirmed=self._on_exe_confirmed,
            on_exe_row_selected=self._on_exe_row_selected,
        )
        self._exe_list = exe.exe_list
        self._exe_confirm_btn = exe.confirm_btn

        redist = build_redist_page(
            self._stack,
            on_apply=self._on_redist_apply,
            on_skip=self._on_redist_skip,
        )
        self._redist_list = redist.list_box
        self._redist_apply_btn = redist.apply_btn
        self._redist_skip_btn = redist.skip_btn
        self._redist_status_label = redist.status_label

        done = build_done_page(self._stack, lambda _: self.close())
        self._done_page = done.page

        err = build_error_page(
            self._stack,
            on_retry=self._on_retry_clicked,
            on_close=lambda _: self.close(),
        )
        self._error_page = err.page

    # ------------------------------------------------------------------
    # Step indicator
    # ------------------------------------------------------------------

    _TOTAL_STEPS = 4  # Choose → Configure → Install → Done

    def _set_step(self, step: int, label: str | None = None) -> None:
        """Update the subtitle with a step indicator like 'Step 1 of 4'."""
        subtitle = f"Step {step} of {self._TOTAL_STEPS}"
        if label:
            subtitle += f" — {label}"
        self._dialog_title.set_subtitle(subtitle)

    # ------------------------------------------------------------------
    # Handlers — file selection & probing
    # ------------------------------------------------------------------

    def _on_choose_clicked(self, _btn: Gtk.Button) -> None:
        f = Gtk.FileFilter()
        f.set_name("Installers & Archives")
        for pat in ("*.exe", "*.msi", "*.zip", "*.7z", "*.rar"):
            f.add_pattern(pat)
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
        self._set_step(1, "Detecting")
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
            elif installer_type == "archive":
                GLib.idle_add(self._on_archive_detected)
            else:
                GLib.idle_add(self._on_generic_detected)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    def _on_probe_done(self, info) -> None:
        self._installer_type = "innosetup"
        self._gog_probe_info = info
        self._install_spinner.set_spinning(False)
        self._dialog_title.set_title(info.title)
        self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._stack.set_visible_child_name("confirm")
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)

        self._set_step(2, "Configure")
        self._title_row.set_subtitle(info.title)
        self._gameid_row.set_subtitle(info.game_id or "N/A")
        self._lang_row.set_subtitle(", ".join(info.languages) or "N/A")

        n = len(self._installer_parts)
        if n == 0:
            self._parts_row.set_subtitle("Single-file installer")
            self._rar_warn_banner.set_revealed(False)
            self._install_btn.set_sensitive(True)
        else:
            self._parts_row.set_subtitle(f"Multi-part: {1 + n} files ({n} .bin parts detected)")
            missing_rar = find_rar_tool() is None
            self._rar_warn_banner.set_revealed(missing_rar)
            self._install_btn.set_sensitive(not missing_rar)

    def _on_generic_detected(self) -> None:
        self._installer_type = "generic"
        assert self._installer_path is not None
        self._install_spinner.set_spinning(False)
        self._dialog_title.set_title(self._installer_path.stem)
        self._set_step(2, "Configure")
        self._generic_file_row.set_subtitle(self._installer_path.name)
        self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._stack.set_visible_child_name("confirm_generic")
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)

    def _on_archive_detected(self) -> None:
        self._installer_type = "archive"
        assert self._installer_path is not None
        self._install_spinner.set_spinning(False)
        self._dialog_title.set_title(self._installer_path.stem)
        self._set_step(2, "Configure")
        self._archive_file_row.set_subtitle(self._installer_path.name)
        self._archive_name_row.set_text(self._installer_path.stem)

        kind = detect_archive_type(self._installer_path)
        if kind and not archive_tool_available(kind):
            if kind == "7z":
                self._archive_tool_warn_banner.set_title(
                    "7z not installed — install p7zip-full to extract this archive."
                )
            else:
                self._archive_tool_warn_banner.set_title(
                    "No RAR tool available — install 'unar' or 'unrar' to extract."
                )
            self._archive_tool_warn_banner.set_revealed(True)
            self._archive_install_btn.set_sensitive(False)
        else:
            self._archive_tool_warn_banner.set_revealed(False)
            self._archive_install_btn.set_sensitive(True)

        self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._stack.set_visible_child_name("confirm_archive")
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)

    # ------------------------------------------------------------------
    # Handlers — GOG install
    # ------------------------------------------------------------------

    def _on_install_clicked(self, _btn: Gtk.Button) -> None:
        if self._gog_wine_row.get_active():
            self._start_gog_wine_install()
            return

        self._set_step(3, "Installing")
        self._stack.set_visible_child_name("installing")
        self._install_spinner.set_spinning(True)
        self._install_status_label.set_label("Installing…")
        self._log_buffer.set_text("")
        self._progress_bar.set_fraction(0)
        self._progress_bar.set_visible(True)

        threading.Thread(target=self._install_thread, daemon=True).start()

    def _start_gog_wine_install(self) -> None:
        """Run the GOG .exe interactively via Wine, then show exe selection."""
        assert self._installer_path is not None
        assert self._gog_probe_info is not None

        from exwin.backend.prefix import prefix_root

        runtime = self._runtimes[self._runtime_row.get_selected()] if self._runtimes else None
        arch = _ARCH_OPTIONS[self._arch_row.get_selected()]
        app_id = app_id_from_info(self._gog_probe_info)
        p_root = prefix_root(app_id, self._config)

        self._generic_prefix_root = p_root
        self._generic_runtime = runtime
        self._generic_arch = arch
        self._gog_wine_mode = True

        self._set_step(3, "Installing")
        self._stack.set_visible_child_name("wine_running")
        threading.Thread(
            target=self._wine_installer_thread,
            args=(self._installer_path, p_root, runtime, arch),
            daemon=True,
        ).start()

    def _install_thread(self) -> None:
        assert self._installer_path is not None

        runtime = self._runtimes[self._runtime_row.get_selected()] if self._runtimes else None
        self._last_install_runtime = runtime
        arch = _ARCH_OPTIONS[self._arch_row.get_selected()]
        verbs_text = self._winetricks_row.get_text().strip()
        verbs = verbs_text.split() if verbs_text else []

        def _file_progress(current: int, total: int) -> None:
            GLib.idle_add(self._update_progress, current, total)

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
                    on_file_progress=_file_progress,
                )
                GLib.idle_add(self._on_install_done, app)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    # ------------------------------------------------------------------
    # Handlers — archive install
    # ------------------------------------------------------------------

    def _on_archive_install_clicked(self, _btn: Gtk.Button) -> None:
        assert self._installer_path is not None
        app_name = self._archive_name_row.get_text().strip() or self._installer_path.stem
        runtime = (
            self._runtimes[self._archive_runtime_row.get_selected()] if self._runtimes else None
        )
        arch = _ARCH_OPTIONS[self._archive_arch_row.get_selected()]
        verbs_text = self._archive_winetricks_row.get_text().strip()
        verbs = verbs_text.split() if verbs_text else []

        self._generic_runtime = runtime
        self._last_install_runtime = runtime
        self._generic_arch = arch

        self._set_step(3, "Installing")
        self._stack.set_visible_child_name("installing")
        self._install_spinner.set_spinning(True)
        self._install_status_label.set_label("Extracting…")
        self._log_buffer.set_text("")
        self._progress_bar.set_fraction(0)
        self._progress_bar.set_visible(True)

        threading.Thread(
            target=self._archive_install_thread,
            args=(
                self._installer_path,
                app_name,
                runtime,
                arch,
                verbs,
                self._archive_dxvk_row.get_active(),
                self._archive_vkd3d_row.get_active(),
            ),
            daemon=True,
        ).start()

    def _archive_install_thread(
        self,
        installer: Path,
        app_name: str,
        runtime: Runtime | None,
        arch: str,
        verbs: list[str],
        dxvk: bool,
        vkd3d: bool,
    ) -> None:
        def _file_progress(current: int, total: int) -> None:
            GLib.idle_add(self._update_progress, current, total)

        try:
            install_dir, candidates = install_archive(
                installer_path=installer,
                app_name=app_name,
                config=self._config,
                on_progress=lambda msg: GLib.idle_add(self._append_log, msg),
                on_file_progress=_file_progress,
            )
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))
            return

        self._archive_install_dir = install_dir
        self._archive_candidates = candidates

        GLib.idle_add(
            self._on_archive_extract_done,
            app_name,
            install_dir,
            candidates,
            runtime,
            arch,
            verbs,
            dxvk,
            vkd3d,
        )

    def _on_archive_extract_done(
        self,
        app_name: str,
        install_dir: Path,
        candidates: list[Path],
        runtime: Runtime | None,
        arch: str,
        verbs: list[str],
        dxvk: bool,
        vkd3d: bool,
    ) -> None:
        self._progress_bar.set_visible(False)

        if not candidates:
            self._on_error(
                "No executables found inside the archive. "
                "The archive may not contain a Windows game, or files were installed "
                "to an unexpected layout."
            )
            return

        # Stash finalise args for use after exe selection
        self._archive_pending = {
            "app_name": app_name,
            "install_dir": install_dir,
            "runtime": runtime,
            "arch": arch,
            "verbs": verbs,
            "dxvk": dxvk,
            "vkd3d": vkd3d,
        }

        if len(candidates) > 1:
            self._populate_exe_select(candidates)
            self._stack.set_visible_child_name("exe_select")
            return

        self._finalize_archive_with_exe(candidates[0])

    def _finalize_archive_with_exe(self, exe_abs: Path) -> None:
        pending = self._archive_pending
        self._install_spinner.set_spinning(True)
        self._install_status_label.set_label("Finalising…")
        self._stack.set_visible_child_name("installing")
        threading.Thread(
            target=self._archive_finalize_thread,
            args=(exe_abs, pending),
            daemon=True,
        ).start()

    def _archive_finalize_thread(self, exe_abs: Path, pending: dict) -> None:
        try:
            app = finalize_archive_install(
                app_name=pending["app_name"],
                install_dir=pending["install_dir"],
                exe_abs=exe_abs,
                config=self._config,
                runtime=pending["runtime"],
                arch=pending["arch"],
                winetricks_verbs=pending["verbs"],
                dxvk=pending["dxvk"],
                vkd3d=pending["vkd3d"],
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
            p_root = base_app.prefix_path
        else:
            from exwin.backend.prefix import prefix_root

            self._generic_dlc_mode = False
            self._generic_dlc_base_app = None
            app_name = self._installer_path.stem
            app_id_slug = app_name.lower().replace(" ", "-")
            p_root = prefix_root(f"manual-{app_id_slug}", self._config)

        self._generic_prefix_root = p_root
        self._generic_runtime = runtime
        self._last_install_runtime = runtime
        self._generic_arch = arch

        self._set_step(3, "Installing")
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
            start = time.monotonic()
            proc.wait()
            elapsed = time.monotonic() - start
            self._wine_proc = None
            rc = proc.returncode

            if rc != 0 and elapsed < 5:
                # Process exited almost immediately with an error — installer never ran
                GLib.idle_add(
                    self._on_error,
                    f"The installer process failed to launch (exit code {rc}).\n"
                    "Check that the selected runtime is installed and working.",
                )
                return

            GLib.idle_add(self._on_wine_installer_done, rc)
        except FileNotFoundError as exc:
            GLib.idle_add(
                self._on_error,
                f"Could not find the runtime binary: {exc}\nMake sure Wine or Proton is installed.",
            )
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    def _on_wine_installer_done(self, rc: int = 0) -> None:
        if self._generic_dlc_mode and self._generic_dlc_base_app is not None:
            self._done_page.set_description(
                f'DLC installed for "{self._generic_dlc_base_app.name}".'
            )
            self._stack.set_visible_child_name("done")
            return

        assert self._generic_prefix_root is not None
        candidates = scan_candidate_exes(self._generic_prefix_root, self._generic_runtime)

        if not candidates:
            if rc != 0:
                self._on_error(
                    f"The installer exited with error code {rc} and no executable was found.\n"
                    "The installation likely failed — check the runtime configuration."
                )
            else:
                self._on_error(
                    "Wine installer finished but no executable was found in the prefix.\n"
                    "The installation may have failed or installed to an unexpected location."
                )
            return

        # When multiple candidates exist, let the user choose
        if len(candidates) > 1:
            self._populate_exe_select(candidates)
            self._stack.set_visible_child_name("exe_select")
            return

        best = pick_best_exe(candidates)
        assert self._installer_path is not None
        if self._gog_wine_mode and self._gog_probe_info is not None:
            app_name = self._gog_probe_info.title
            verbs_text = self._winetricks_row.get_text().strip()
        else:
            app_name = self._installer_path.stem
            verbs_text = self._generic_winetricks_row.get_text().strip()
        verbs = verbs_text.split() if verbs_text else []

        self._stack.set_visible_child_name("installing")
        self._install_spinner.set_spinning(True)
        self._install_status_label.set_label("Finalising…")
        self._log_buffer.set_text("")

        threading.Thread(
            target=self._finalize_thread,
            args=(app_name, best, verbs),
            daemon=True,
        ).start()

    def _populate_exe_select(self, candidates: list[Path]) -> None:
        """Fill the exe selection list box with candidate executables."""
        while (child := self._exe_list.get_first_child()) is not None:
            self._exe_list.remove(child)

        best = pick_best_exe(candidates)
        first_row = None
        for exe in candidates:
            row = Adw.ActionRow(title=exe.name, subtitle=str(exe.parent))
            row.exe_path = exe  # type: ignore[attr-defined]
            self._exe_list.append(row)
            if exe == best and first_row is None:
                first_row = row

        # Pre-select the best guess
        if first_row is not None:
            self._exe_list.select_row(first_row)
            self._exe_confirm_btn.set_sensitive(True)

    def _on_exe_row_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        self._exe_confirm_btn.set_sensitive(row is not None)

    def _on_exe_confirmed(self, _btn: Gtk.Button) -> None:
        row = self._exe_list.get_selected_row()
        if row is None:
            return

        exe_abs: Path = row.exe_path  # type: ignore[attr-defined]
        assert self._installer_path is not None

        # Archive flow owns its own finaliser — no Wine prefix involved yet.
        if self._installer_type == "archive":
            self._finalize_archive_with_exe(exe_abs)
            return

        assert self._generic_prefix_root is not None

        if self._gog_wine_mode and self._gog_probe_info is not None:
            app_name = self._gog_probe_info.title
            verbs_text = self._winetricks_row.get_text().strip()
        else:
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

        app_id_override = None
        source_override = AppSource.MANUAL
        if self._gog_wine_mode and self._gog_probe_info is not None:
            app_id_override = app_id_from_info(self._gog_probe_info)
            source_override = AppSource.GOG

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
                app_id_override=app_id_override,
                source_override=source_override,
            )
            GLib.idle_add(self._on_install_done, app)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    def _on_cancel_wine(self, _btn: Gtk.Button) -> None:
        if self._wine_proc is not None:
            self._wine_proc.terminate()
        self._gog_wine_mode = False
        self._stack.set_visible_child_name("welcome")
        self._installer_path = None
        self._dialog_title.set_title("Install Game")

    # ------------------------------------------------------------------
    # Shared handlers
    # ------------------------------------------------------------------

    def _on_gog_wine_toggled(self, switch_row: Adw.SwitchRow, _pspec) -> None:
        is_wine = switch_row.get_active()
        self._install_btn.set_label("Run Installer" if is_wine else "Install")
        # DLC mode and Wine mode are mutually exclusive
        self._dlc_switch_row.set_sensitive(not is_wine and bool(self._base_games))
        if is_wine and self._dlc_switch_row.get_active():
            self._dlc_switch_row.set_active(False)

    def _on_dlc_toggled(self, switch_row: Adw.SwitchRow, _pspec) -> None:
        self._base_game_row.set_visible(switch_row.get_active())

    def _on_generic_dlc_toggled(self, switch_row: Adw.SwitchRow, _pspec) -> None:
        self._generic_base_game_row.set_visible(switch_row.get_active())

    def _on_install_done(self, app: AppEntry) -> None:
        self._install_spinner.set_spinning(False)
        self._progress_bar.set_visible(False)
        self._on_installed(app)

        findings: list[RedistFinding] = []
        if app.install_path and self._last_install_runtime is not None:
            try:
                findings = redist_scanner.scan(app.install_path)
            except Exception:
                findings = []

        if findings:
            self._redist_app = app
            self._redist_runtime = self._last_install_runtime
            self._redist_findings = findings
            self._populate_redist_list(findings)
            self._set_step(4, "Prerequisites")
            self._stack.set_visible_child_name("redist")
        else:
            self._set_step(4, "Done")
            self._done_page.set_description(f'"{app.name}" is ready to play.')
            self._stack.set_visible_child_name("done")

    # ------------------------------------------------------------------
    # Redist page handlers
    # ------------------------------------------------------------------

    def _populate_redist_list(self, findings: list[RedistFinding]) -> None:
        while (child := self._redist_list.get_first_child()) is not None:
            self._redist_list.remove(child)
        self._redist_checks = {}

        for finding in findings:
            row = Adw.ActionRow(title=finding.description, subtitle=finding.path.name)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.set_active(finding.recommended)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            tag_label = Gtk.Label(
                label=("verb: " + finding.payload) if finding.action == "verb" else "run installer",
                valign=Gtk.Align.CENTER,
            )
            tag_label.add_css_class("caption")
            tag_label.add_css_class("dim-label")
            row.add_suffix(tag_label)
            self._redist_list.append(row)
            self._redist_checks[finding.kind] = check

        self._redist_status_label.set_label(
            f"Found {len(findings)} bundled prerequisite{'s' if len(findings) != 1 else ''}."
        )

    def _on_redist_apply(self, _btn: Gtk.Button) -> None:
        selected = [f for f in self._redist_findings if self._redist_checks[f.kind].get_active()]
        if not selected:
            self._finish_redist_flow()
            return
        self._redist_apply_btn.set_sensitive(False)
        self._redist_skip_btn.set_sensitive(False)
        self._redist_status_label.set_label("Applying…")
        threading.Thread(target=self._redist_apply_thread, args=(selected,), daemon=True).start()

    def _on_redist_skip(self, _btn: Gtk.Button) -> None:
        self._finish_redist_flow()

    def _redist_apply_thread(self, findings: list[RedistFinding]) -> None:
        assert self._redist_app is not None
        assert self._redist_runtime is not None
        prefix_root = self._redist_app.prefix_path
        for f in findings:
            GLib.idle_add(self._redist_status_label.set_label, f"Applying: {f.description}")
            try:
                apply_finding(f, prefix_root, self._redist_runtime)
            except Exception as exc:
                GLib.idle_add(
                    self._redist_status_label.set_label,
                    f"Failed: {f.description} ({exc})",
                )
        GLib.idle_add(self._finish_redist_flow)

    def _finish_redist_flow(self) -> None:
        self._redist_apply_btn.set_sensitive(True)
        self._redist_skip_btn.set_sensitive(True)
        app = self._redist_app
        self._set_step(4, "Done")
        if app is not None:
            self._done_page.set_description(f'"{app.name}" is ready to play.')
        self._stack.set_visible_child_name("done")

    def _on_dlc_install_done(self, dlc_title: str, base_name: str) -> None:
        self._install_spinner.set_spinning(False)
        self._set_step(4, "Done")
        self._done_page.set_description(f'DLC installed for "{base_name}".')
        self._stack.set_visible_child_name("done")

    def _on_error(self, message: str) -> None:
        self._install_spinner.set_spinning(False)
        self._progress_bar.set_visible(False)
        self._error_page.set_description(message)
        self._stack.set_visible_child_name("error")

    def _on_retry_clicked(self, _btn: Gtk.Button) -> None:
        self._installer_path = None
        self._gog_wine_mode = False
        self._dialog_title.set_title("Install Game")
        self._stack.set_visible_child_name("welcome")

    def _update_progress(self, current: int, total: int) -> None:
        if total > 0:
            fraction = min(current / total, 1.0)
            self._progress_bar.set_fraction(fraction)
            self._progress_bar.set_text(f"{current} / {total} files")
        else:
            self._progress_bar.pulse()
            self._progress_bar.set_text(f"{current} files")

    def _append_log(self, line: str) -> None:
        end = self._log_buffer.get_end_iter()
        self._log_buffer.insert(end, line + "\n")
        adj = self._log_scroll.get_vadjustment()
        adj.set_value(adj.get_upper())
