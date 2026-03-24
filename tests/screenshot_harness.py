"""Visual screenshot harness — captures real UI screenshots for inspection.

Usage: xvfb-run --auto-servernum .venv/bin/python tests/screenshot_harness.py
Output: /tmp/exwin_screenshots/*.png
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Disable all libadwaita/GTK animations so dialogs appear instantly
os.environ["ADW_DISABLE_ANIMATIONS"] = "1"

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GLib, Graphene, Gtk  # noqa: E402

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

OUT_DIR = Path("/tmp/exwin_screenshots")
OUT_DIR.mkdir(exist_ok=True)

_app = Adw.Application(application_id="io.github.exwin.test.screenshots")
_app.register()

# Force dark theme for consistent screenshots
style_mgr = _app.get_style_manager()
style_mgr.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

# Disable animations at the toolkit level too
gtk_settings = Gtk.Settings.get_default()
if gtk_settings:
    gtk_settings.set_property("gtk-enable-animations", False)


def _pump(n: int = 200, sleep: float = 0) -> None:
    import time

    ctx = GLib.MainContext.default()
    for _ in range(n):
        while ctx.pending():
            ctx.iteration(False)
        ctx.iteration(False)
    if sleep > 0:
        # Process events during the sleep window too
        end = time.monotonic() + sleep
        while time.monotonic() < end:
            while ctx.pending():
                ctx.iteration(False)
            time.sleep(0.01)


def _screenshot_widget(widget: Gtk.Widget, name: str, *, width: int = 0, height: int = 0) -> Path:
    """Render a widget to PNG. Returns the output path."""
    _pump()
    w = width or widget.get_width()
    h = height or widget.get_height()
    if w <= 0 or h <= 0:
        print(f"  WARNING: {name} has zero size ({w}x{h}), skipping")
        return OUT_DIR / f"{name}.png"

    paintable = Gtk.WidgetPaintable.new(widget)
    snapshot = Gtk.Snapshot.new()
    paintable.snapshot(snapshot, w, h)
    node = snapshot.to_node()
    if not node:
        print(f"  WARNING: {name} produced no render node")
        return OUT_DIR / f"{name}.png"

    native = widget.get_native()
    if native is None:
        print(f"  WARNING: {name} has no native surface")
        return OUT_DIR / f"{name}.png"

    renderer = native.get_renderer()
    rect = Graphene.Rect()
    rect.init(0, 0, w, h)
    texture = renderer.render_texture(node, rect)
    out_path = OUT_DIR / f"{name}.png"
    texture.save_to_png(str(out_path))
    print(f"  Captured: {out_path} ({w}x{h})")
    return out_path


def _screenshot_dialog_in_window(
    dialog_widget: Gtk.Widget,
    name: str,
    *,
    win_width: int = 1100,
    win_height: int = 700,
) -> Path:
    """Present an Adw.Dialog on a host window and capture the full window."""
    win = Adw.ApplicationWindow(application=_app)
    win.set_default_size(win_width, win_height)
    # Give the window a dark placeholder so the dialog stands out
    placeholder = Gtk.Box()
    placeholder.add_css_class("background")
    win.set_content(placeholder)
    win.present()
    _pump()

    dialog_widget.present(win)
    _pump(300)

    path = _screenshot_widget(win, name)
    dialog_widget.force_close()
    _pump()
    win.destroy()
    _pump()
    return path


# ---------------------------------------------------------------------------
# Load real data
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exwin.backend.app_config import AppConfig, load_app_config  # noqa: E402
from exwin.backend.config import Config  # noqa: E402
from exwin.backend.runtime import Runtime  # noqa: E402
from exwin.db.apps import get_all_apps  # noqa: E402
from exwin.db.runtimes import get_all_runtimes, sync_runtimes  # noqa: E402
from exwin.db.schema import init_db  # noqa: E402

cfg = Config.load()
init_db(cfg.data_dir)
from exwin.backend.runtime import scan_runtimes  # noqa: E402

sync_runtimes(scan_runtimes())

runtimes = get_all_runtimes()
apps = get_all_apps()

print(f"Loaded {len(apps)} app(s), {len(runtimes)} runtime(s)")
for a in apps:
    print(f"  - {a.name} ({a.app_id})")

# Find Balrum (or use first app)
balrum = next((a for a in apps if "balrum" in a.name.lower()), apps[0] if apps else None)
if not balrum:
    print("ERROR: No apps in library — install a game first")
    sys.exit(1)

print(f"\nUsing app: {balrum.name} ({balrum.app_id})")
runtime = next((r for r in runtimes if r.db_id == balrum.runtime_id), runtimes[0] if runtimes else None)
app_config = load_app_config(balrum.app_id, cfg)


# ---------------------------------------------------------------------------
# Screenshot 1: Main Window (Library view)
# ---------------------------------------------------------------------------
print("\n=== 1. Main Window — Library View ===")

from exwin.backend.launcher import Launcher  # noqa: E402
from exwin.window import ExwinWindow  # noqa: E402

launcher = Launcher(cfg)
main_win = ExwinWindow(
    config=cfg,
    runtimes=runtimes,
    launcher=launcher,
    application=_app,
)
main_win.present()
_pump(300)
_screenshot_widget(main_win, "01_main_window_library")


# ---------------------------------------------------------------------------
# Screenshot 2: App Detail Dialog
# ---------------------------------------------------------------------------
print("\n=== 2. App Detail Dialog ===")

from exwin.ui.app_detail_dialog import AppDetailDialog  # noqa: E402

detail_dialog = AppDetailDialog(
    app=balrum,
    is_running=False,
    config=cfg,
    runtime=runtime,
    on_launch=lambda a: None,
    on_stop=lambda a: None,
    on_uninstall=lambda a, d: None,
    on_settings_saved=lambda aid, ac: None,
    on_paths_changed=lambda a: None,
    runtimes=runtimes,
    launcher=launcher,
)
detail_dialog.present(main_win)
_pump(500, sleep=0.5)
_screenshot_widget(main_win, "02_app_detail_dialog")
detail_dialog.force_close()
_pump(200, sleep=0.3)


# ---------------------------------------------------------------------------
# Screenshot 3: App Settings Dialog
# ---------------------------------------------------------------------------
print("\n=== 3. App Settings Dialog ===")

from exwin.ui.app_settings_dialog import AppSettingsDialog  # noqa: E402

settings_dialog = AppSettingsDialog(
    app=balrum,
    app_config=app_config,
    config=cfg,
    runtime=runtime,
    on_saved=lambda ac: None,
    runtimes=runtimes,
)
settings_dialog.present(main_win)
_pump(500, sleep=0.5)
_screenshot_widget(main_win, "03_app_settings_dialog")
settings_dialog.force_close()
_pump(200, sleep=0.3)


# ---------------------------------------------------------------------------
# Screenshot 4: Install Dialog (welcome page)
# ---------------------------------------------------------------------------
print("\n=== 4. Install Dialog (Welcome) ===")

from exwin.ui.install_dialog import InstallDialog  # noqa: E402

install_dialog = InstallDialog(
    config=cfg,
    runtimes=runtimes,
    on_installed=lambda a: None,
)
install_dialog.present(main_win)
_pump(500, sleep=0.5)
_screenshot_widget(main_win, "04_install_dialog_welcome")
install_dialog.force_close()
_pump(200, sleep=0.3)


# ---------------------------------------------------------------------------
# Screenshot 5: Add Existing Game Dialog
# ---------------------------------------------------------------------------
print("\n=== 5. Add Existing Game Dialog ===")

from exwin.ui.add_existing_dialog import AddExistingDialog  # noqa: E402

add_dialog = AddExistingDialog(
    config=cfg,
    runtimes=runtimes,
    on_added=lambda a: None,
)
add_dialog.present(main_win)
_pump(500, sleep=0.5)
_screenshot_widget(main_win, "05_add_existing_dialog")
add_dialog.force_close()
_pump(200, sleep=0.3)


# ---------------------------------------------------------------------------
# Screenshot 6: Settings Page
# ---------------------------------------------------------------------------
print("\n=== 6. Settings Page ===")

# Navigate to settings page
main_win._nav_list.select_row(main_win._nav_list.get_row_at_index(1))
_pump(300)
_screenshot_widget(main_win, "06_settings_page")

# Navigate back to library
main_win._nav_list.select_row(main_win._nav_list.get_row_at_index(0))
_pump()


# ---------------------------------------------------------------------------
# Screenshot 7: Log Viewer Dialog (create a dummy log first)
# ---------------------------------------------------------------------------
print("\n=== 7. Log Viewer Dialog ===")

log_path = cfg.logs_dir / f"{balrum.app_id}.log"
if not log_path.exists():
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "Starting Balrum with GE-Proton10-32...\n"
        "STEAM_COMPAT_DATA_PATH=/games/games/exwin/prefixes/gog-1769415595\n"
        "Running: /path/to/proton run Balrum.exe\n"
        "fsync: up and running.\n"
        "wine: configuration in L\"C:\\\\users\\\\steamuser\" has been updated.\n"
        "Game process exited with code 0\n"
    )

from exwin.ui.log_viewer_dialog import LogViewerDialog  # noqa: E402

log_dialog = LogViewerDialog(app_name=balrum.name, log_path=log_path)
log_dialog.present(main_win)
_pump(500, sleep=0.5)
_screenshot_widget(main_win, "07_log_viewer_dialog")
log_dialog.force_close()
_pump(200, sleep=0.3)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
main_win.destroy()
_pump()

print(f"\nAll screenshots saved to {OUT_DIR}/")
print("Done.")
