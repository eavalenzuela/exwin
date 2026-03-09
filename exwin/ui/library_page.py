"""Library page — grid of app cards with search/filter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, Gtk, Pango  # noqa: E402

from exwin.models import AppEntry  # noqa: E402

# Width of each card in the flow grid
_CARD_WIDTH = 160

# Sort options: (label, key function)
_SORT_OPTIONS = [
    ("Name", lambda a: a.name.lower()),
    ("Last Played", lambda a: a.last_launched or ""),
    ("Play Time", lambda a: a.playtime_seconds),
    ("Install Date", lambda a: a.install_date or ""),
]

# Source filter options
_SOURCE_FILTERS = ["All", "GOG", "Manual"]


def _fmt_playtime(seconds: int) -> str:
    if seconds < 60:
        return "< 1m"
    h, m = divmod(seconds // 60, 60)
    return f"{h}h {m}m" if h else f"{m}m"


class LibraryPage(Gtk.Box):
    """Main library view: search bar + flow grid of app cards."""

    def __init__(
        self,
        on_app_activated: Callable[[AppEntry], None],
        on_installer_dropped: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_app_activated = on_app_activated
        self._on_installer_dropped = on_installer_dropped

        # Drag-and-drop: accept .exe files dropped onto the library
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_drop)
        self.add_controller(drop_target)
        self._sort_index = 0
        self._sort_descending = False
        self._source_filter = "All"
        self._tag_filter = "All"

        # ── Search bar ──────────────────────────────────────────────────
        self._search_entry = Gtk.SearchEntry(placeholder_text="Search library…")
        self._search_entry.connect("search-changed", self._on_search_changed)

        self.search_bar = Gtk.SearchBar(show_close_button=True)
        self.search_bar.set_child(self._search_entry)
        self.search_bar.connect_entry(self._search_entry)
        self.append(self.search_bar)

        # ── Sort / filter bar ───────────────────────────────────────────
        controls_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_start=16,
            margin_end=16,
            margin_top=8,
            margin_bottom=0,
        )
        self.append(controls_box)

        # Sort dropdown
        sort_model = Gtk.StringList()
        for label, _ in _SORT_OPTIONS:
            sort_model.append(label)
        self._sort_dropdown = Gtk.DropDown(model=sort_model)
        self._sort_dropdown.set_tooltip_text("Sort by")
        self._sort_dropdown.connect("notify::selected", self._on_sort_changed)
        controls_box.append(Gtk.Label(label="Sort:"))
        controls_box.append(self._sort_dropdown)

        # Sort direction toggle
        self._sort_dir_btn = Gtk.ToggleButton(icon_name="view-sort-ascending-symbolic")
        self._sort_dir_btn.set_tooltip_text("Toggle sort direction")
        self._sort_dir_btn.connect("toggled", self._on_sort_dir_toggled)
        controls_box.append(self._sort_dir_btn)

        # Source filter dropdown
        filter_model = Gtk.StringList()
        for label in _SOURCE_FILTERS:
            filter_model.append(label)
        self._filter_dropdown = Gtk.DropDown(model=filter_model)
        self._filter_dropdown.set_tooltip_text("Filter by source")
        self._filter_dropdown.connect("notify::selected", self._on_filter_changed)
        controls_box.append(Gtk.Label(label="Source:"))
        controls_box.append(self._filter_dropdown)

        # Tag filter dropdown (populated dynamically)
        self._tag_model = Gtk.StringList()
        self._tag_model.append("All")
        self._tag_dropdown = Gtk.DropDown(model=self._tag_model)
        self._tag_dropdown.set_tooltip_text("Filter by tag")
        self._tag_dropdown.connect("notify::selected", self._on_tag_filter_changed)
        controls_box.append(Gtk.Label(label="Tag:"))
        controls_box.append(self._tag_dropdown)

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
        self._apps = list(apps)
        self._running_ids = running_ids
        self._refresh_tag_dropdown()
        self._rebuild_grid()

    def _refresh_tag_dropdown(self) -> None:
        """Rebuild the tag filter dropdown from current apps."""
        all_tags: set[str] = set()
        for app in self._apps:
            all_tags.update(app.tag_list)
        tags = sorted(all_tags)

        # Preserve selection if possible
        prev = self._tag_filter

        while self._tag_model.get_n_items() > 0:
            self._tag_model.remove(0)
        self._tag_model.append("All")
        for t in tags:
            self._tag_model.append(t)

        # Re-select previous tag if still available
        idx = 0
        if prev != "All":
            for i, t in enumerate(tags, start=1):
                if t == prev:
                    idx = i
                    break
            else:
                self._tag_filter = "All"
        self._tag_dropdown.set_selected(idx)

    def toggle_search(self) -> None:
        self.search_bar.set_search_mode(not self.search_bar.get_search_mode())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_grid(self) -> None:
        """Re-sort, filter, and repopulate the FlowBox."""
        while (child := self._flow_box.get_first_child()) is not None:
            self._flow_box.remove(child)

        # Apply source filter
        apps = self._apps
        if self._source_filter != "All":
            source_key = self._source_filter.lower()
            apps = [a for a in apps if a.source == source_key]

        # Apply tag filter
        if self._tag_filter != "All":
            apps = [a for a in apps if self._tag_filter in a.tag_list]

        # Apply sort
        _, key_fn = _SORT_OPTIONS[self._sort_index]
        # Name sorts ascending by default; date/playtime sort descending by default
        reverse = self._sort_descending
        if self._sort_index == 0:
            # Name: ascending natural, toggle reverses
            pass
        else:
            # Date/playtime: descending natural (most recent/highest first)
            reverse = not reverse
        apps = sorted(apps, key=key_fn, reverse=reverse)

        for app in apps:
            self._flow_box.append(_AppCard(app, is_running=app.app_id in self._running_ids))

        self._stack.set_visible_child_name("grid" if apps else "empty")
        self._flow_box.invalidate_filter()

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

    def _on_sort_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        self._sort_index = dropdown.get_selected()
        if hasattr(self, "_apps"):
            self._rebuild_grid()

    def _on_sort_dir_toggled(self, btn: Gtk.ToggleButton) -> None:
        self._sort_descending = btn.get_active()
        btn.set_icon_name(
            "view-sort-descending-symbolic"
            if self._sort_descending
            else "view-sort-ascending-symbolic"
        )
        if hasattr(self, "_apps"):
            self._rebuild_grid()

    def _on_filter_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        idx = dropdown.get_selected()
        self._source_filter = _SOURCE_FILTERS[idx]
        if hasattr(self, "_apps"):
            self._rebuild_grid()

    def _on_tag_filter_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        idx = dropdown.get_selected()
        item = self._tag_model.get_string(idx)
        self._tag_filter = item or "All"
        if hasattr(self, "_apps"):
            self._rebuild_grid()

    def _on_drop(self, _target: Gtk.DropTarget, value: Gdk.FileList, _x: float, _y: float) -> bool:
        files = value.get_files()
        for gfile in files:
            fpath = Path(gfile.get_path())
            if fpath.suffix.lower() == ".exe" and self._on_installer_dropped:
                self._on_installer_dropped(fpath)
                return True
        return False

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
        cover.update_property([Gtk.AccessibleProperty.LABEL], [f"Cover art for {app.name}"])
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

        if app.playtime_seconds > 0:
            pt_label = Gtk.Label(label=_fmt_playtime(app.playtime_seconds))
            pt_label.add_css_class("caption")
            pt_label.add_css_class("dim-label")
            pt_label.set_halign(Gtk.Align.START)
            label_box.append(pt_label)

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
