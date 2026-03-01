"""Library page — grid of app cards with search/filter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk, Pango  # noqa: E402

from exwin.models import AppEntry  # noqa: E402

# Width of each card in the flow grid
_CARD_WIDTH = 160


class LibraryPage(Gtk.Box):
    """Main library view: search bar + flow grid of app cards."""

    def __init__(self, on_app_activated: Callable[[AppEntry], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_app_activated = on_app_activated

        # ── Search bar ──────────────────────────────────────────────────
        self._search_entry = Gtk.SearchEntry(placeholder_text="Search library…")
        self._search_entry.connect("search-changed", self._on_search_changed)

        self.search_bar = Gtk.SearchBar(show_close_button=True)
        self.search_bar.set_child(self._search_entry)
        self.search_bar.connect_entry(self._search_entry)
        self.append(self.search_bar)

        # ── Content stack (empty state / grid) ──────────────────────────
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self.append(self._stack)

        # Empty state
        empty = Adw.StatusPage(
            title="No Apps Installed",
            description='Click "Install Game" to add your first game.',
            icon_name="applications-games-symbolic",
        )
        self._stack.add_named(empty, "empty")

        # Grid (scrollable FlowBox)
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._stack.add_named(scroll, "grid")

        self._flow_box = Gtk.FlowBox()
        self._flow_box.set_valign(Gtk.Align.START)
        self._flow_box.set_homogeneous(True)
        self._flow_box.set_min_children_per_line(2)
        self._flow_box.set_max_children_per_line(12)
        self._flow_box.set_column_spacing(12)
        self._flow_box.set_row_spacing(12)
        self._flow_box.set_margin_top(16)
        self._flow_box.set_margin_bottom(16)
        self._flow_box.set_margin_start(16)
        self._flow_box.set_margin_end(16)
        self._flow_box.set_filter_func(self._filter_func)
        self._flow_box.connect("child-activated", self._on_child_activated)
        scroll.set_child(self._flow_box)

        self._stack.set_visible_child_name("empty")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def populate(self, apps: list[AppEntry], running_ids: frozenset[str] = frozenset()) -> None:
        """Replace the current card set with the given app list."""
        while (child := self._flow_box.get_first_child()) is not None:
            self._flow_box.remove(child)

        for app in apps:
            self._flow_box.append(_AppCard(app, is_running=app.app_id in running_ids))

        self._stack.set_visible_child_name("grid" if apps else "empty")

    def toggle_search(self) -> None:
        self.search_bar.set_search_mode(not self.search_bar.get_search_mode())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _filter_func(self, child: Gtk.FlowBoxChild) -> bool:
        query = self._search_entry.get_text().lower().strip()
        if not query:
            return True
        card = child.get_child()
        if not isinstance(card, _AppCard):
            return True
        return query in card.app.name.lower()

    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        self._flow_box.invalidate_filter()

    def _on_child_activated(self, _fb: Gtk.FlowBox, child: Gtk.FlowBoxChild) -> None:
        card = child.get_child()
        if isinstance(card, _AppCard):
            self._on_app_activated(card.app)


# ---------------------------------------------------------------------------
# App card widget
# ---------------------------------------------------------------------------


class _AppCard(Gtk.Box):
    """A single app card displayed in the library grid."""

    def __init__(self, app: AppEntry, *, is_running: bool = False) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.app = app
        self.set_size_request(_CARD_WIDTH, -1)
        self.add_css_class("card")

        # Cover art
        if app.cover_art_path and Path(app.cover_art_path).exists():
            cover: Gtk.Widget = Gtk.Picture.new_for_filename(app.cover_art_path)
            cover.set_content_fit(Gtk.ContentFit.COVER)  # type: ignore[attr-defined]
        else:
            cover = Gtk.Image()
            cover.set_from_icon_name("applications-games-symbolic")
            cover.set_pixel_size(64)
        cover.set_size_request(_CARD_WIDTH, 220)
        cover.set_overflow(Gtk.Overflow.HIDDEN)
        self.append(cover)

        # Label area
        label_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            margin_top=8,
            margin_bottom=8,
            margin_start=8,
            margin_end=8,
        )
        self.append(label_box)

        name_label = Gtk.Label(label=app.name)
        name_label.add_css_class("caption-heading")
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.set_halign(Gtk.Align.START)
        name_label.set_max_width_chars(20)
        label_box.append(name_label)

        # Bottom row: source badge + optional running indicator
        bottom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        label_box.append(bottom_row)

        source_label = Gtk.Label(label=app.source.upper())
        source_label.add_css_class("caption")
        source_label.add_css_class("dim-label")
        source_label.set_halign(Gtk.Align.START)
        source_label.set_hexpand(True)
        bottom_row.append(source_label)

        if is_running:
            running_dot = Gtk.Label(label="▶")
            running_dot.add_css_class("caption")
            running_dot.add_css_class("success")
            running_dot.set_tooltip_text("Running")
            bottom_row.append(running_dot)
