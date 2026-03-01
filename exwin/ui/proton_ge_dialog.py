"""Dialog for downloading and installing Proton-GE releases."""

from __future__ import annotations

import threading
from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from exwin.backend.proton_ge import (  # noqa: E402
    download_and_install,
    find_ge_proton_asset,
    get_latest_release,
    is_installed,
)


class ProtonGEDialog(Adw.Dialog):
    """Fetch and download the latest Proton-GE release."""

    def __init__(
        self,
        on_installed: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(title="Download Proton-GE", content_width=420, **kwargs)
        self._on_installed = on_installed
        self._release: dict | None = None

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        toolbar_view.set_content(self._stack)

        self._build_loading_page()
        self._build_confirm_page()
        self._build_downloading_page()
        self._build_done_page()
        self._build_error_page()

        self._stack.set_visible_child_name("loading")
        threading.Thread(target=self._fetch_thread, daemon=True).start()

    # ------------------------------------------------------------------
    # Page builders
    # ------------------------------------------------------------------

    def _build_loading_page(self) -> None:
        page = Adw.StatusPage(
            title="Checking for updates…",
            icon_name="software-update-available-symbolic",
        )
        spinner = Gtk.Spinner()
        spinner.set_spinning(True)
        spinner.set_size_request(32, 32)
        spinner.set_halign(Gtk.Align.CENTER)
        page.set_child(spinner)
        self._stack.add_named(page, "loading")

    def _build_confirm_page(self) -> None:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
            margin_top=24,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
            vexpand=True,
            valign=Gtk.Align.CENTER,
        )

        self._confirm_title = Gtk.Label()
        self._confirm_title.add_css_class("title-2")
        self._confirm_title.set_wrap(True)
        self._confirm_title.set_halign(Gtk.Align.CENTER)
        box.append(self._confirm_title)

        self._confirm_desc = Gtk.Label()
        self._confirm_desc.add_css_class("body")
        self._confirm_desc.add_css_class("dim-label")
        self._confirm_desc.set_wrap(True)
        self._confirm_desc.set_halign(Gtk.Align.CENTER)
        box.append(self._confirm_desc)

        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            halign=Gtk.Align.CENTER,
        )
        box.append(btn_box)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.add_css_class("pill")
        cancel_btn.connect("clicked", lambda _: self.close())
        btn_box.append(cancel_btn)

        download_btn = Gtk.Button(label="Download")
        download_btn.add_css_class("suggested-action")
        download_btn.add_css_class("pill")
        download_btn.connect("clicked", self._on_download_clicked)
        btn_box.append(download_btn)

        self._stack.add_named(box, "confirm")

    def _build_downloading_page(self) -> None:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
            margin_top=24,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
            vexpand=True,
            valign=Gtk.Align.CENTER,
        )

        self._dl_label = Gtk.Label(label="Downloading…")
        self._dl_label.add_css_class("title-4")
        box.append(self._dl_label)

        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.set_show_text(True)
        box.append(self._progress_bar)

        self._stack.add_named(box, "downloading")

    def _build_done_page(self) -> None:
        page = Adw.StatusPage(
            title="Proton-GE Installed",
            description="Restart exwin or go to Settings to see the new runtime.",
            icon_name="emblem-ok-symbolic",
        )
        close_btn = Gtk.Button(label="Done")
        close_btn.add_css_class("suggested-action")
        close_btn.add_css_class("pill")
        close_btn.connect("clicked", lambda _: self.close())
        page.set_child(close_btn)
        self._stack.add_named(page, "done")

    def _build_error_page(self) -> None:
        self._error_page = Adw.StatusPage(
            title="Download Failed",
            icon_name="dialog-error-symbolic",
        )
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            halign=Gtk.Align.CENTER,
        )
        retry_btn = Gtk.Button(label="Retry")
        retry_btn.add_css_class("pill")
        retry_btn.connect("clicked", self._on_retry)
        close_btn = Gtk.Button(label="Close")
        close_btn.add_css_class("destructive-action")
        close_btn.add_css_class("pill")
        close_btn.connect("clicked", lambda _: self.close())
        btn_box.append(retry_btn)
        btn_box.append(close_btn)
        self._error_page.set_child(btn_box)
        self._stack.add_named(self._error_page, "error")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_download_clicked(self, _btn: Gtk.Button) -> None:
        self._stack.set_visible_child_name("downloading")
        threading.Thread(target=self._download_thread, daemon=True).start()

    def _on_retry(self, _btn: Gtk.Button) -> None:
        self._stack.set_visible_child_name("loading")
        threading.Thread(target=self._fetch_thread, daemon=True).start()

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def _fetch_thread(self) -> None:
        try:
            release = get_latest_release()
            GLib.idle_add(self._on_fetch_done, release)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    def _on_fetch_done(self, release: dict) -> None:
        self._release = release
        tag = release.get("tag_name", "unknown")

        try:
            asset = find_ge_proton_asset(release)
            size_mb = asset.get("size", 0) / (1024 * 1024)
            size_str = f"{size_mb:.0f} MB"
        except RuntimeError:
            size_str = "unknown size"

        if is_installed(tag):
            self._confirm_title.set_label(f"{tag} — already installed")
            self._confirm_desc.set_label("This version is already present in compatibilitytools.d.")
        else:
            self._confirm_title.set_label(f"Download {tag}?")
            self._confirm_desc.set_label(
                f"Will be extracted to ~/.steam/root/compatibilitytools.d  ({size_str})"
            )

        self._stack.set_visible_child_name("confirm")

    def _download_thread(self) -> None:
        assert self._release is not None
        try:
            download_and_install(
                self._release,
                on_progress=lambda dl, total: GLib.idle_add(self._on_progress, dl, total),
            )
            GLib.idle_add(self._on_download_done)
        except Exception as exc:
            GLib.idle_add(self._on_error, str(exc))

    def _on_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            self._progress_bar.set_fraction(downloaded / total)
            pct = int(downloaded / total * 100)
            mb = downloaded / (1024 * 1024)
            self._progress_bar.set_text(f"{pct}%  ({mb:.1f} MB)")
        else:
            self._progress_bar.pulse()
            mb = downloaded / (1024 * 1024)
            self._progress_bar.set_text(f"{mb:.1f} MB downloaded")

    def _on_download_done(self) -> None:
        self._stack.set_visible_child_name("done")
        self._on_installed()

    def _on_error(self, message: str) -> None:
        self._error_page.set_description(message)
        self._stack.set_visible_child_name("error")
