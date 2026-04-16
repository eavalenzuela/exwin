"""Winetricks verb picker dialog and drop-in row widget.

``WinetricksRow`` is an ``Adw.ActionRow`` that exposes ``get_text()`` /
``set_text()`` (space-separated verb list) so it can replace an
``Adw.EntryRow`` at any of the existing call sites without API changes.

Clicking the row's *Edit…* button opens ``WinetricksPicker`` — a modal with
a search entry, quick-apply preset buttons, and category-grouped checkboxes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from exwin.backend.winetricks_catalog import (  # noqa: E402
    POPULAR_NAMES,
    PRESETS,
    Verb,
    is_available,
    load_catalog,
)


class WinetricksRow(Adw.ActionRow):
    """An Adw.ActionRow with an Edit… suffix that opens the picker.

    Exposes ``get_text()`` / ``set_text()`` returning a space-joined list of
    selected verbs so this drops in wherever a plain ``Adw.EntryRow`` was used.
    """

    def __init__(self, title: str = "Winetricks Verbs", parent: Gtk.Widget | None = None) -> None:
        super().__init__(title=title)
        self._parent = parent
        self._base_title = title
        self._verbs: list[str] = []
        self._available = is_available()

        self.edit_btn = Gtk.Button(label="Edit…", valign=Gtk.Align.CENTER)
        self.edit_btn.add_css_class("flat")
        self.edit_btn.connect("clicked", self._on_edit_clicked)
        self.add_suffix(self.edit_btn)
        self.set_activatable_widget(self.edit_btn)

        if not self._available:
            self.edit_btn.set_sensitive(False)
            self.set_subtitle("winetricks not installed")
        else:
            self.set_subtitle("No verbs selected")

    # ------------------------------------------------------------------
    # EntryRow-compatible API
    # ------------------------------------------------------------------

    def get_text(self) -> str:
        return " ".join(self._verbs)

    def set_text(self, text: str) -> None:
        self._verbs = [v for v in text.split() if v]
        self._refresh_subtitle()

    def set_sensitive(self, sensitive: bool) -> None:  # type: ignore[override]
        super().set_sensitive(sensitive)
        self.edit_btn.set_sensitive(sensitive and self._available)

    def set_title(self, title: str) -> None:  # type: ignore[override]
        self._base_title = title
        super().set_title(title)

    def set_tooltip_text(self, text: str) -> None:  # type: ignore[override]
        super().set_tooltip_text(text)
        self.edit_btn.set_tooltip_text(text)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_subtitle(self) -> None:
        if not self._verbs:
            self.set_subtitle("No verbs selected")
        elif len(self._verbs) <= 4:
            self.set_subtitle(" ".join(self._verbs))
        else:
            preview = " ".join(self._verbs[:3])
            self.set_subtitle(f"{preview} … (+{len(self._verbs) - 3} more)")

    def _on_edit_clicked(self, _btn: Gtk.Button) -> None:
        picker = WinetricksPicker(
            initial=self._verbs,
            on_apply=self._on_picker_apply,
        )
        parent = self._parent or self.get_root()
        picker.present(parent)

    def _on_picker_apply(self, verbs: list[str]) -> None:
        self._verbs = verbs
        self._refresh_subtitle()


class WinetricksPicker(Adw.Dialog):
    """Modal picker for selecting winetricks verbs."""

    def __init__(
        self,
        initial: list[str],
        on_apply: Callable[[list[str]], None],
    ) -> None:
        super().__init__(title="Winetricks Verbs", content_width=560, content_height=640)
        self._on_apply = on_apply
        self._selected: set[str] = set(initial)
        self._rows: dict[str, Gtk.CheckButton] = {}
        self._all_verbs: list[Verb] = []

        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)

        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)

        apply_btn = Gtk.Button(label="Apply")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self._on_apply_clicked)
        header.pack_end(apply_btn)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        toolbar.set_content(self._stack)

        loading = Adw.StatusPage(title="Loading verbs…")
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        spinner.set_halign(Gtk.Align.CENTER)
        loading.set_child(spinner)
        self._stack.add_named(loading, "loading")

        self._build_main_page()

        self._stack.set_visible_child_name("loading")
        threading.Thread(target=self._load_thread, daemon=True).start()

    # ------------------------------------------------------------------
    # Main page
    # ------------------------------------------------------------------

    def _build_main_page(self) -> None:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        self._search = Gtk.SearchEntry(placeholder_text="Search verbs…")
        self._search.connect("search-changed", self._on_search_changed)
        box.append(self._search)

        preset_group = Adw.PreferencesGroup(title="Presets")
        preset_row = Adw.ActionRow()
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, hexpand=True)
        preset_box.set_margin_top(6)
        preset_box.set_margin_bottom(6)
        for name, verbs in PRESETS.items():
            btn = Gtk.Button(label=name)
            btn.add_css_class("pill")
            btn.connect("clicked", self._on_preset_clicked, verbs)
            preset_box.append(btn)
        preset_row.set_child(preset_box)
        preset_group.add(preset_row)
        box.append(preset_group)

        self._selected_label = Gtk.Label(xalign=0, wrap=True)
        self._selected_label.add_css_class("dim-label")
        self._selected_label.add_css_class("caption")
        box.append(self._selected_label)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.append(scroll)

        self._groups_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll.set_child(self._groups_box)

        self._stack.add_named(box, "main")

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_thread(self) -> None:
        verbs = load_catalog()
        GLib.idle_add(self._on_catalog_loaded, verbs)

    def _on_catalog_loaded(self, verbs: list[Verb]) -> None:
        self._all_verbs = verbs
        self._populate_groups(verbs)
        self._refresh_selected_label()
        self._stack.set_visible_child_name("main")

    def _populate_groups(self, verbs: list[Verb]) -> None:
        while (child := self._groups_box.get_first_child()) is not None:
            self._groups_box.remove(child)
        self._rows.clear()

        popular = [v for v in verbs if v.name in POPULAR_NAMES]
        by_cat: dict[str, list[Verb]] = {}
        for v in verbs:
            by_cat.setdefault(v.category, []).append(v)

        if popular:
            self._groups_box.append(self._build_group("Popular", popular))
        for cat in sorted(by_cat):
            self._groups_box.append(
                self._build_group(cat, sorted(by_cat[cat], key=lambda v: v.name))
            )

    def _build_group(self, title: str, verbs: list[Verb]) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=title)
        for verb in verbs:
            row = Adw.ActionRow(title=verb.name, subtitle=verb.description)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.set_active(verb.name in self._selected)
            check.connect("toggled", self._on_verb_toggled, verb.name)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            group.add(row)
            # Multiple rows can reference the same verb (Popular + category);
            # keep the first reference so toggling syncs via _selected state.
            self._rows.setdefault(verb.name, check)
        return group

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        query = entry.get_text().strip().lower()
        if not query:
            self._populate_groups(self._all_verbs)
            return
        filtered = [
            v for v in self._all_verbs if query in v.name.lower() or query in v.description.lower()
        ]
        self._populate_groups(filtered)

    def _on_verb_toggled(self, check: Gtk.CheckButton, name: str) -> None:
        if check.get_active():
            self._selected.add(name)
        else:
            self._selected.discard(name)
        # Sync duplicate checkboxes (verb can appear in Popular and category).
        tracked = self._rows.get(name)
        if tracked and tracked is not check and tracked.get_active() != check.get_active():
            tracked.set_active(check.get_active())
        self._refresh_selected_label()

    def _on_preset_clicked(self, _btn: Gtk.Button, verbs: list[str]) -> None:
        for v in verbs:
            self._selected.add(v)
            check = self._rows.get(v)
            if check and not check.get_active():
                check.set_active(True)
        self._refresh_selected_label()

    def _on_apply_clicked(self, _btn: Gtk.Button) -> None:
        # Preserve catalog order rather than set iteration order.
        catalog_order = {v.name: i for i, v in enumerate(self._all_verbs)}
        ordered = sorted(self._selected, key=lambda n: catalog_order.get(n, 10_000))
        self._on_apply(ordered)
        self.close()

    def _refresh_selected_label(self) -> None:
        if not self._selected:
            self._selected_label.set_label("No verbs selected")
        else:
            self._selected_label.set_label(
                f"{len(self._selected)} selected: {' '.join(sorted(self._selected))}"
            )
