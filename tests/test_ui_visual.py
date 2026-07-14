"""Visual layout tests — instantiate UI widgets and check for sizing/layout issues.

These tests create real GTK widgets under Xvfb, force layout computation, and
assert that nothing is clipped, collapsed, or improperly sized.

Run:  xvfb-run .venv/bin/pytest tests/test_ui_visual.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# GTK bootstrap — must happen once before any widget is created
# ---------------------------------------------------------------------------

_gtk_app = None


def _ensure_gtk() -> None:
    """Initialize GTK/Adw once per process."""
    global _gtk_app
    if _gtk_app is not None:
        return

    import gi

    gi.require_version("Adw", "1")
    gi.require_version("Gtk", "4.0")

    from gi.repository import Adw

    _gtk_app = Adw.Application(application_id="io.github.exwin.test.visual")
    _gtk_app.register()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_entry(**overrides) -> AppEntry:
    from exwin.models import AppEntry, AppSource

    defaults = dict(
        app_id="test-game-1",
        name="Test Game With a Reasonably Long Title",
        source=AppSource.GOG,
        install_path=Path("/tmp/exwin-test/apps/test-game-1"),
        prefix_path=Path("/tmp/exwin-test/prefixes/test-game-1"),
        exe_path="game.exe",
        cover_art_path="",
        description="A test game used for visual layout validation.",
        install_date="2025-01-15T12:00:00",
        last_launched="2025-06-01T18:30:00",
        runtime_id=1,
        playtime_seconds=7200,
        tags="rpg,action",
    )
    defaults.update(overrides)
    return AppEntry(**defaults)


def _make_runtime() -> Runtime:
    from exwin.backend.runtime import Runtime
    from exwin.models import RuntimeType

    return Runtime(
        name="Proton-GE 9-1",
        type=RuntimeType.PROTON,
        path=Path("/home/user/.steam/root/compatibilitytools.d/GE-Proton9-1"),
        version="9-1",
    )


def _make_config(tmp_path: Path) -> Config:
    from exwin.backend.config import Config

    cfg = Config(data_dir=tmp_path / "exwin")
    cfg._ensure_dirs()
    return cfg


def _pump_events(iterations: int = 50) -> None:
    """Process pending GTK events to force layout computation."""
    from gi.repository import GLib

    ctx = GLib.MainContext.default()
    for _ in range(iterations):
        ctx.iteration(False)


def _realize_in_window(widget, *, width: int = 1100, height: int = 700) -> Gtk.Window:
    """Place a widget in a temporary window and realize it for measurement."""
    from gi.repository import Gtk

    win = Gtk.Window()
    win.set_default_size(width, height)
    win.set_child(widget)
    win.present()
    _pump_events()
    return win


def _measure_natural(widget) -> tuple[int, int]:
    """Return (natural_width, natural_height) of a widget.

    GTK4 measure() returns (minimum, natural, min_baseline, nat_baseline).
    """
    from gi.repository import Gtk

    _min_w, nat_w, _mb_w, _nb_w = widget.measure(Gtk.Orientation.HORIZONTAL, -1)
    _min_h, nat_h, _mb_h, _nb_h = widget.measure(Gtk.Orientation.VERTICAL, -1)
    return nat_w, nat_h


def _get_allocated_size(widget) -> tuple[int, int]:
    """Return the allocated (width, height) after layout."""
    return widget.get_width(), widget.get_height()


class VisualIssue:
    """Represents a detected visual problem."""

    def __init__(self, widget_name: str, issue: str, details: str = "") -> None:
        self.widget_name = widget_name
        self.issue = issue
        self.details = details

    def __repr__(self) -> str:
        s = f"[{self.widget_name}] {self.issue}"
        if self.details:
            s += f" — {self.details}"
        return s


def _check_widget_tree(widget, *, path: str = "", issues: list | None = None) -> list[VisualIssue]:
    """Walk the widget tree and flag common visual problems.

    Skips GTK internal widgets (scrollbars, revealers, gizmos) that naturally
    have zero allocation when inactive — these are normal GTK behaviour.
    """
    from gi.repository import Gtk

    # Widget classes whose zero-allocation is expected GTK behaviour
    _SKIP_CLASSES = {"GtkScrollbar", "GtkRevealer", "GtkGizmo", "GtkRange"}

    if issues is None:
        issues = []

    name = widget.get_name() or widget.__class__.__name__
    full_path = f"{path}/{name}" if path else name

    if not widget.get_visible():
        return issues  # Skip hidden subtrees

    # Skip GTK internal widgets that are normally zero-sized
    type_name = type(widget).__name__
    # Also match GObject-style names like "GtkScrollbar"
    gtype_name = widget.__class__.__gtype__.name if hasattr(widget.__class__, "__gtype__") else ""
    if type_name in _SKIP_CLASSES or gtype_name in _SKIP_CLASSES:
        return issues
    # Skip children inside a scrollbar/revealer/range parent
    for skip in _SKIP_CLASSES:
        if f"/{skip}/" in full_path or full_path.endswith(f"/{skip}"):
            return issues

    w, h = _get_allocated_size(widget)

    # Flag widgets that claim to want space but got allocated nothing
    _min_w, nat_w, _mb_w, _nb_w = widget.measure(Gtk.Orientation.HORIZONTAL, -1)
    _min_h, nat_h, _mb_h, _nb_h = widget.measure(Gtk.Orientation.VERTICAL, -1)

    if nat_w > 0 and w == 0:
        issues.append(
            VisualIssue(full_path, "zero width allocation", f"natural={nat_w}, alloc={w}")
        )
    if nat_h > 0 and h == 0:
        issues.append(
            VisualIssue(full_path, "zero height allocation", f"natural={nat_h}, alloc={h}")
        )

    # Check for severely clipped content (allocated < 30% of natural size)
    if nat_w > 100 and w > 0 and w < nat_w * 0.3:
        issues.append(
            VisualIssue(full_path, "severely clipped width", f"natural={nat_w}, alloc={w}")
        )
    if nat_h > 100 and h > 0 and h < nat_h * 0.3:
        issues.append(
            VisualIssue(full_path, "severely clipped height", f"natural={nat_h}, alloc={h}")
        )

    # Recurse into children
    child = widget.get_first_child()
    while child is not None:
        _check_widget_tree(child, path=full_path, issues=issues)
        child = child.get_next_sibling()

    return issues


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _gtk_init():
    _ensure_gtk()


@pytest.fixture
def visual_config(tmp_path: Path):
    return _make_config(tmp_path)


@pytest.fixture
def sample_app():
    return _make_app_entry()


@pytest.fixture
def sample_runtime():
    return _make_runtime()


@pytest.fixture
def sample_app_config():
    from exwin.backend.app_config import AppConfig

    return AppConfig()


# ---------------------------------------------------------------------------
# Tests: AppDetailDialog
# ---------------------------------------------------------------------------


@pytest.mark.ui
class TestAppDetailDialogVisual:
    """Visual checks for the app detail dialog."""

    def test_dialog_has_content_height(self) -> None:
        """The dialog must set content_height to avoid collapsing."""
        from exwin.ui.app_detail_dialog import AppDetailDialog

        app = _make_app_entry()
        config = _make_config(Path("/tmp/exwin-visual-test"))
        runtime = _make_runtime()

        dialog = AppDetailDialog(
            app=app,
            is_running=False,
            config=config,
            runtime=runtime,
            on_launch=lambda a: None,
            on_stop=lambda a: None,
            on_uninstall=lambda a, d: None,
        )
        # content_height property should be > 0
        ch = dialog.get_content_height()
        assert ch >= 400, f"content_height too small: {ch}"

    def test_dialog_has_content_width(self) -> None:
        from exwin.ui.app_detail_dialog import AppDetailDialog

        app = _make_app_entry()
        config = _make_config(Path("/tmp/exwin-visual-test"))

        dialog = AppDetailDialog(
            app=app,
            is_running=False,
            config=config,
            runtime=None,
            on_launch=lambda a: None,
            on_stop=lambda a: None,
            on_uninstall=lambda a, d: None,
        )
        cw = dialog.get_content_width()
        assert cw >= 300, f"content_width too small: {cw}"

    def test_dialog_child_is_not_none(self) -> None:
        from exwin.ui.app_detail_dialog import AppDetailDialog

        app = _make_app_entry()
        config = _make_config(Path("/tmp/exwin-visual-test"))

        dialog = AppDetailDialog(
            app=app,
            is_running=False,
            config=config,
            runtime=None,
            on_launch=lambda a: None,
            on_stop=lambda a: None,
            on_uninstall=lambda a, d: None,
        )
        assert dialog.get_child() is not None, "Dialog has no child widget"


# ---------------------------------------------------------------------------
# Tests: InstallDialog
# ---------------------------------------------------------------------------


@pytest.mark.ui
class TestInstallDialogVisual:
    """Visual checks for the install dialog."""

    def test_dialog_has_content_width(self, visual_config) -> None:
        from exwin.db.schema import init_db
        from exwin.ui.install_dialog import InstallDialog

        init_db(visual_config.data_dir)
        dialog = InstallDialog(
            config=visual_config,
            runtimes=[_make_runtime()],
            on_installed=lambda a: None,
        )
        cw = dialog.get_content_width()
        assert cw >= 400, f"InstallDialog content_width too small: {cw}"

    def test_dialog_has_content_height(self, visual_config) -> None:
        from exwin.db.schema import init_db
        from exwin.ui.install_dialog import InstallDialog

        init_db(visual_config.data_dir)
        dialog = InstallDialog(
            config=visual_config,
            runtimes=[_make_runtime()],
            on_installed=lambda a: None,
        )
        ch = dialog.get_content_height()
        # InstallDialog currently might be missing content_height
        assert ch >= 400, (
            f"InstallDialog content_height={ch} — dialog will collapse to minimal size. "
            "Add content_height= to the super().__init__() call."
        )

    def test_welcome_page_is_default(self, visual_config) -> None:
        from exwin.db.schema import init_db
        from exwin.ui.install_dialog import InstallDialog

        init_db(visual_config.data_dir)
        dialog = InstallDialog(
            config=visual_config,
            runtimes=[_make_runtime()],
            on_installed=lambda a: None,
        )
        # Should start on the welcome page
        stack = dialog._stack
        assert stack.get_visible_child_name() == "welcome"


# ---------------------------------------------------------------------------
# Tests: InstallDialog auto-detection plan page
# ---------------------------------------------------------------------------


@pytest.mark.ui
class TestInstallDialogAutoPlan:
    """The analyze → auto-plan review flow populates pages and mirrors widgets."""

    def _dialog(self, visual_config):
        from exwin.db.schema import init_db
        from exwin.ui.install_dialog import InstallDialog

        init_db(visual_config.data_dir)
        return InstallDialog(
            config=visual_config,
            runtimes=[_make_runtime()],
            on_installed=lambda a: None,
        )

    def _archive_plan(self, tmp_path: Path):
        from exwin.backend.auto_detect import InstallPlan

        installer = tmp_path / "Koihime Musou.part1.exe"
        installer.touch()
        return InstallPlan(
            installer_path=installer,
            route="archive",
            tech="rar-sfx",
            title="Koihime Musou",
            archive_kind="rar",
            parts=[tmp_path / "Koihime Musou.part2.rar"],
            runtime_index=0,
            runtime_name="Proton-GE 9-1",
            dxvk=False,
            vkd3d=False,
            reasons=["Self-extracting archive — extract directly."],
        )

    def test_analyze_shows_auto_plan_page(self, visual_config, tmp_path: Path) -> None:
        dialog = self._dialog(visual_config)
        plan = self._archive_plan(tmp_path)
        dialog._installer_path = plan.installer_path
        dialog._on_analyze_done(plan)
        assert dialog._stack.get_visible_child_name() == "auto_plan"
        assert dialog._auto_title_row.get_subtitle() == "Koihime Musou"
        assert "2 parts" in dialog._auto_type_row.get_subtitle()
        assert dialog._auto_install_btn.get_sensitive()

    def test_plan_mirrors_into_manual_page(self, visual_config, tmp_path: Path) -> None:
        dialog = self._dialog(visual_config)
        plan = self._archive_plan(tmp_path)
        dialog._installer_path = plan.installer_path
        dialog._on_analyze_done(plan)
        assert dialog._archive_name_row.get_text() == "Koihime Musou"
        assert dialog._archive_runtime_row.get_selected() == 0
        assert dialog._archive_arch_row.get_selected() == 0  # win64
        assert dialog._archive_dxvk_row.get_active() is False

    def test_configure_manually_routes_by_plan(self, visual_config, tmp_path: Path) -> None:
        dialog = self._dialog(visual_config)
        plan = self._archive_plan(tmp_path)
        dialog._installer_path = plan.installer_path
        dialog._on_analyze_done(plan)
        dialog._on_configure_manually_clicked(None)
        assert dialog._stack.get_visible_child_name() == "confirm_archive"

    def test_blocked_plan_disables_auto_install(self, visual_config, tmp_path: Path) -> None:
        dialog = self._dialog(visual_config)
        plan = self._archive_plan(tmp_path)
        plan.blocked = True
        plan.warnings = ["No RAR tool available."]
        dialog._installer_path = plan.installer_path
        dialog._on_analyze_done(plan)
        assert not dialog._auto_install_btn.get_sensitive()
        assert dialog._auto_warn_banner.get_revealed()

    def test_gog_plan_populates_confirm_page(self, visual_config, tmp_path: Path) -> None:
        from exwin.backend.auto_detect import InstallPlan
        from exwin.backend.gog_installer import InstallerInfo

        dialog = self._dialog(visual_config)
        installer = tmp_path / "setup_balrum_1.03.exe"
        installer.touch()
        info = InstallerInfo(title="Balrum", game_id="1436885438", setup_version="5.5.7")
        plan = InstallPlan(
            installer_path=installer,
            route="gog",
            tech="innosetup-gog",
            title="Balrum",
            game_id="1436885438",
            probe_info=info,
            runtime_index=0,
            runtime_name="Proton-GE 9-1",
            reasons=["GOG offline installer."],
        )
        dialog._installer_path = installer
        dialog._on_analyze_done(plan)
        assert dialog._stack.get_visible_child_name() == "auto_plan"
        assert dialog._title_row.get_subtitle() == "Balrum"
        assert dialog._gameid_row.get_subtitle() == "1436885438"
        dialog._on_configure_manually_clicked(None)
        assert dialog._stack.get_visible_child_name() == "confirm"


# ---------------------------------------------------------------------------
# Tests: AddExistingDialog
# ---------------------------------------------------------------------------


@pytest.mark.ui
class TestAddExistingDialogVisual:
    """Visual checks for the add-existing-game dialog."""

    def test_dialog_dimensions(self, visual_config) -> None:
        from exwin.ui.add_existing_dialog import AddExistingDialog

        dialog = AddExistingDialog(
            config=visual_config,
            runtimes=[_make_runtime()],
            on_added=lambda a: None,
        )
        cw = dialog.get_content_width()
        ch = dialog.get_content_height()
        assert cw >= 400, f"AddExistingDialog content_width too small: {cw}"
        assert ch >= 400, f"AddExistingDialog content_height too small: {ch}"


# ---------------------------------------------------------------------------
# Tests: AppSettingsDialog
# ---------------------------------------------------------------------------


@pytest.mark.ui
class TestAppSettingsDialogVisual:
    """Visual checks for the per-app settings dialog."""

    def test_dialog_has_content_height(self, visual_config) -> None:
        from exwin.backend.app_config import AppConfig
        from exwin.ui.app_settings_dialog import AppSettingsDialog

        dialog = AppSettingsDialog(
            app=_make_app_entry(),
            app_config=AppConfig(),
            config=visual_config,
            runtime=_make_runtime(),
            on_saved=lambda c: None,
            runtimes=[_make_runtime()],
        )
        ch = dialog.get_content_height()
        assert ch >= 400, (
            f"AppSettingsDialog content_height={ch} — dialog will collapse. "
            "Add content_height= to the super().__init__() call."
        )

    def test_dialog_has_content_width(self, visual_config) -> None:
        from exwin.backend.app_config import AppConfig
        from exwin.ui.app_settings_dialog import AppSettingsDialog

        dialog = AppSettingsDialog(
            app=_make_app_entry(),
            app_config=AppConfig(),
            config=visual_config,
            runtime=_make_runtime(),
            on_saved=lambda c: None,
        )
        cw = dialog.get_content_width()
        assert cw >= 400, f"AppSettingsDialog content_width too small: {cw}"

    def test_auto_configure_applies_to_widgets(self, visual_config) -> None:
        from exwin.backend.app_config import AppConfig
        from exwin.ui.app_settings_dialog import AppSettingsDialog

        dialog = AppSettingsDialog(
            app=_make_app_entry(),
            app_config=AppConfig(),
            config=visual_config,
            runtime=_make_runtime(),
            on_saved=lambda c: None,
            runtimes=[_make_runtime()],
        )
        recommended = AppConfig(
            gamemode=True,
            nvapi=True,
            dxvk_state_cache=True,
            winetricks_verbs=["vcrun2019"],
        )
        dialog._apply_config_to_widgets(recommended)
        assert dialog._gamemode_row.get_active() is True
        assert dialog._nvapi_row.get_active() is True
        assert dialog._dxvk_cache_row.get_active() is True
        assert dialog._winetricks_row.get_text() == "vcrun2019"


# ---------------------------------------------------------------------------
# Tests: ProtonGEDialog
# ---------------------------------------------------------------------------


@pytest.mark.ui
class TestProtonGEDialogVisual:
    """Visual checks for the Proton-GE download dialog."""

    def test_dialog_has_content_height(self) -> None:
        from exwin.ui.proton_ge_dialog import ProtonGEDialog

        dialog = ProtonGEDialog(on_installed=lambda: None)
        ch = dialog.get_content_height()
        assert ch >= 300, (
            f"ProtonGEDialog content_height={ch} — dialog will collapse. "
            "Add content_height= to the super().__init__() call."
        )


# ---------------------------------------------------------------------------
# Tests: LogViewerDialog
# ---------------------------------------------------------------------------


@pytest.mark.ui
class TestLogViewerDialogVisual:
    """Visual checks for the log viewer dialog."""

    def test_dialog_dimensions(self, tmp_path) -> None:
        from exwin.ui.log_viewer_dialog import LogViewerDialog

        log_file = tmp_path / "test.log"
        log_file.write_text("line 1\nline 2\nline 3\n")

        dialog = LogViewerDialog(app_name="Test Game", log_path=log_file)
        cw = dialog.get_content_width()
        ch = dialog.get_content_height()
        assert cw >= 400, f"LogViewerDialog content_width too small: {cw}"
        assert ch >= 400, f"LogViewerDialog content_height too small: {ch}"


# ---------------------------------------------------------------------------
# Tests: SettingsPage
# ---------------------------------------------------------------------------


@pytest.mark.ui
class TestSettingsPageVisual:
    """Visual checks for the global settings page."""

    def test_page_creates_without_error(self, visual_config) -> None:
        from exwin.ui.settings_page import SettingsPage

        page = SettingsPage(config=visual_config, runtimes=[_make_runtime()])
        assert page is not None

    def test_page_has_natural_size(self, visual_config) -> None:
        from exwin.ui.settings_page import SettingsPage

        page = SettingsPage(config=visual_config, runtimes=[])
        nat_w, nat_h = _measure_natural(page)
        assert nat_w > 0, "SettingsPage has zero natural width"
        assert nat_h > 0, "SettingsPage has zero natural height"

    def test_page_shows_version(self, visual_config) -> None:
        from exwin import __version__
        from exwin.ui.settings_page import SettingsPage

        page = SettingsPage(config=visual_config, runtimes=[])
        assert __version__ in page._version_row.get_subtitle()


# ---------------------------------------------------------------------------
# Tests: LibraryPage
# ---------------------------------------------------------------------------


@pytest.mark.ui
class TestLibraryPageVisual:
    """Visual checks for the library grid page."""

    def test_page_creates_without_error(self) -> None:
        from exwin.ui.library_page import LibraryPage

        page = LibraryPage(on_app_activated=lambda a: None)
        assert page is not None

    def test_page_with_apps_has_natural_size(self) -> None:

        from exwin.ui.library_page import LibraryPage

        page = LibraryPage(on_app_activated=lambda a: None)
        apps = [_make_app_entry(app_id=f"game-{i}", name=f"Game {i}") for i in range(6)]
        page.populate(apps)

        win = _realize_in_window(page)
        w, h = _get_allocated_size(page)
        assert w > 200, f"LibraryPage allocated width too small: {w}"
        assert h > 100, f"LibraryPage allocated height too small: {h}"
        win.destroy()

    def test_empty_library_is_valid(self) -> None:
        from exwin.ui.library_page import LibraryPage

        page = LibraryPage(on_app_activated=lambda a: None)
        page.populate([])
        # Should not raise


# ---------------------------------------------------------------------------
# Tests: ExwinWindow (full window assembly)
# ---------------------------------------------------------------------------


@pytest.mark.ui
class TestExwinWindowVisual:
    """Visual checks for the main application window."""

    def test_window_creates_and_shows(self, visual_config) -> None:
        from unittest.mock import MagicMock

        from exwin.db.schema import init_db
        from exwin.window import ExwinWindow

        init_db(visual_config.data_dir)
        launcher = MagicMock()
        launcher.is_running.return_value = False

        win = ExwinWindow(
            config=visual_config,
            runtimes=[_make_runtime()],
            launcher=launcher,
            application=_gtk_app,
        )
        win.present()
        _pump_events()

        w, h = _get_allocated_size(win)
        assert w >= 400, f"Window width too small: {w}"
        assert h >= 300, f"Window height too small: {h}"

        # Check the widget tree for zero-allocation issues
        # Filter out inactive GtkStack children and GtkDropDown internals,
        # which naturally have zero allocation when not visible.
        issues = _check_widget_tree(win)
        critical = [
            i
            for i in issues
            if "zero" in i.issue
            and "/GtkStack/" not in i.widget_name  # inactive stack pages
            and "/GtkDropDown/" not in i.widget_name  # dropdown internals
        ]
        assert not critical, "Widgets with zero allocation:\n" + "\n".join(str(i) for i in critical)

        win.destroy()
        _pump_events()

    def test_sidebar_and_stack_visible(self, visual_config) -> None:
        from unittest.mock import MagicMock

        from exwin.db.schema import init_db
        from exwin.window import ExwinWindow

        init_db(visual_config.data_dir)
        launcher = MagicMock()
        launcher.is_running.return_value = False

        win = ExwinWindow(
            config=visual_config,
            runtimes=[],
            launcher=launcher,
            application=_gtk_app,
        )
        win.present()
        _pump_events()

        # The main stack should show "library" by default
        assert win._stack.get_visible_child_name() == "library"

        win.destroy()
        _pump_events()


# ---------------------------------------------------------------------------
# Tests: Cross-dialog consistency
# ---------------------------------------------------------------------------


@pytest.mark.ui
class TestDialogConsistency:
    """Check that all Adw.Dialog subclasses set required sizing properties."""

    def test_all_dialogs_have_content_width(self, visual_config) -> None:
        """Every dialog must set content_width to avoid being too narrow."""
        from exwin.db.schema import init_db

        init_db(visual_config.data_dir)
        dialogs = self._create_all_dialogs(visual_config)
        for name, dialog in dialogs.items():
            cw = dialog.get_content_width()
            assert cw >= 300, f"{name} content_width={cw} — too narrow"

    def test_all_dialogs_have_content_height(self, visual_config) -> None:
        """Every dialog must set content_height to prevent collapse."""
        from exwin.db.schema import init_db

        init_db(visual_config.data_dir)
        dialogs = self._create_all_dialogs(visual_config)
        failures = []
        for name, dialog in dialogs.items():
            ch = dialog.get_content_height()
            if ch < 300:
                failures.append(f"{name}: content_height={ch}")
        assert not failures, (
            "Dialogs missing content_height (will collapse to minimal size):\n"
            + "\n".join(failures)
        )

    @staticmethod
    def _create_all_dialogs(config) -> dict:
        from exwin.backend.app_config import AppConfig
        from exwin.ui.add_existing_dialog import AddExistingDialog
        from exwin.ui.app_detail_dialog import AppDetailDialog
        from exwin.ui.app_settings_dialog import AppSettingsDialog
        from exwin.ui.install_dialog import InstallDialog
        from exwin.ui.log_viewer_dialog import LogViewerDialog
        from exwin.ui.proton_ge_dialog import ProtonGEDialog

        app = _make_app_entry()
        runtime = _make_runtime()
        noop = lambda *a, **k: None

        log_path = config.logs_dir / "test.log"
        log_path.write_text("test log\n")

        return {
            "AppDetailDialog": AppDetailDialog(
                app=app,
                is_running=False,
                config=config,
                runtime=runtime,
                on_launch=noop,
                on_stop=noop,
                on_uninstall=noop,
            ),
            "InstallDialog": InstallDialog(
                config=config,
                runtimes=[runtime],
                on_installed=noop,
            ),
            "AddExistingDialog": AddExistingDialog(
                config=config,
                runtimes=[runtime],
                on_added=noop,
            ),
            "AppSettingsDialog": AppSettingsDialog(
                app=app,
                app_config=AppConfig(),
                config=config,
                runtime=runtime,
                on_saved=noop,
                runtimes=[runtime],
            ),
            "ProtonGEDialog": ProtonGEDialog(on_installed=noop),
            "LogViewerDialog": LogViewerDialog(app_name="Test", log_path=log_path),
        }
