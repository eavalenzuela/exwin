"""ProtonDB lookup dialog — show tier + report-mined tweaks and apply them."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from exwin.backend.app_config import AppConfig, save_app_config  # noqa: E402
from exwin.backend.config import Config  # noqa: E402
from exwin.backend.protondb import (  # noqa: E402
    ProtonTweaks,
    extract_tweaks,
    fetch_summary,
    fetch_top_reports,
)
from exwin.backend.steam_appid import resolve_steam_appid  # noqa: E402
from exwin.db.apps import update_protondb_cache  # noqa: E402
from exwin.models import AppEntry  # noqa: E402

_TIER_COLORS: dict[str, str] = {
    "platinum": "success",
    "gold": "accent",
    "silver": "accent",
    "bronze": "warning",
    "borked": "error",
    "pending": "",
}


def protondb_cache_dir(config: Config):
    """Directory used for ProtonDB JSON caches."""
    path = config.data_dir / "cache" / "protondb"
    path.mkdir(parents=True, exist_ok=True)
    return path


class ProtonDBDialog(Adw.Dialog):
    """Look up ProtonDB data for an app and optionally apply suggested tweaks."""

    def __init__(
        self,
        app: AppEntry,
        app_config: AppConfig,
        config: Config,
        on_toast: Callable[[str], None] | None = None,
        on_config_saved: Callable[[AppConfig], None] | None = None,
    ) -> None:
        super().__init__(title="ProtonDB", content_width=560, content_height=600)
        self._app = app
        self._app_config = app_config
        self._config = config
        self._on_toast = on_toast
        self._on_config_saved = on_config_saved
        self._tweaks = ProtonTweaks()
        self._tweak_checks: dict[str, Gtk.CheckButton] = {}
        self._tweak_rows: list[Gtk.Widget] = []
        self._appid: int | None = app.steam_appid

        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)
        toolbar.add_top_bar(Adw.HeaderBar())

        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        toolbar.set_content(self._stack)

        self._build_loading_page()
        self._build_unresolved_page()
        self._build_results_page()
        self._build_done_page()

        self._stack.set_visible_child_name("loading")
        threading.Thread(target=self._lookup_thread, daemon=True).start()

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def _build_loading_page(self) -> None:
        page = Adw.StatusPage(title="Checking ProtonDB…")
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        spinner.set_halign(Gtk.Align.CENTER)
        page.set_child(spinner)
        self._stack.add_named(page, "loading")

    def _build_unresolved_page(self) -> None:
        page = Adw.StatusPage(
            title="No Steam match",
            description=(
                "Couldn't resolve a Steam app ID from the game name. "
                "Enter one manually if you know it."
            ),
            icon_name="system-search-symbolic",
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER)
        self._manual_entry = Gtk.Entry(placeholder_text="Steam app ID (e.g. 620)")
        self._manual_entry.set_width_chars(20)
        box.append(self._manual_entry)
        btn = Gtk.Button(label="Look up")
        btn.add_css_class("pill")
        btn.add_css_class("suggested-action")
        btn.connect("clicked", self._on_manual_lookup)
        box.append(btn)
        page.set_child(box)
        self._stack.add_named(page, "unresolved")

    def _build_results_page(self) -> None:
        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
            vexpand=True,
        )

        # Summary (tier + counts)
        self._summary_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.append(self._summary_box)

        # Tweaks group
        self._tweaks_group = Adw.PreferencesGroup(
            title="Suggested tweaks",
            description="Mined from recent reports; uncheck any you don't want.",
        )
        content.append(self._tweaks_group)

        # Reports preview
        reports_group = Adw.PreferencesGroup(title="Recent reports")
        content.append(reports_group)
        self._reports_list = Gtk.ListBox()
        self._reports_list.add_css_class("boxed-list")
        self._reports_list.set_selection_mode(Gtk.SelectionMode.NONE)
        reports_group.add(self._reports_list)

        # Action buttons
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            halign=Gtk.Align.END,
            margin_top=8,
        )
        close = Gtk.Button(label="Close")
        close.add_css_class("pill")
        close.connect("clicked", lambda _: self.close())
        btn_box.append(close)
        self._apply_btn = Gtk.Button(label="Apply tweaks")
        self._apply_btn.add_css_class("pill")
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.connect("clicked", self._on_apply_clicked)
        btn_box.append(self._apply_btn)
        content.append(btn_box)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True, child=content)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._stack.add_named(scroll, "results")

    def _build_done_page(self) -> None:
        page = Adw.StatusPage(
            title="Tweaks applied",
            description="Settings saved to this app's config.",
            icon_name="emblem-ok-symbolic",
        )
        close = Gtk.Button(label="Close")
        close.add_css_class("pill")
        close.connect("clicked", lambda _: self.close())
        page.set_child(close)
        self._stack.add_named(page, "done")

    # ------------------------------------------------------------------
    # Background work
    # ------------------------------------------------------------------

    def _lookup_thread(self) -> None:
        appid = self._appid
        if appid is None:
            appid = resolve_steam_appid(self._app.name)
        if appid is None:
            GLib.idle_add(self._stack.set_visible_child_name, "unresolved")
            return
        self._run_lookup(appid)

    def _run_lookup(self, appid: int) -> None:
        cache_dir = protondb_cache_dir(self._config)
        summary = fetch_summary(appid, cache_dir=cache_dir)
        reports = fetch_top_reports(appid, cache_dir=cache_dir)
        tweaks = extract_tweaks(reports)
        GLib.idle_add(self._on_lookup_done, appid, summary, reports, tweaks)

    def _on_manual_lookup(self, _btn: Gtk.Button) -> None:
        raw = self._manual_entry.get_text().strip()
        try:
            appid = int(raw)
        except ValueError:
            if self._on_toast:
                self._on_toast("Enter a numeric Steam app ID")
            return
        self._stack.set_visible_child_name("loading")
        threading.Thread(target=self._run_lookup, args=(appid,), daemon=True).start()

    def _on_lookup_done(
        self,
        appid: int,
        summary: dict | None,
        reports: list[dict],
        tweaks: ProtonTweaks,
    ) -> None:
        self._appid = appid
        self._tweaks = tweaks

        tier = (summary or {}).get("tier", "") if isinstance(summary, dict) else ""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            update_protondb_cache(self._app.app_id, appid, tier, now)
            self._app.steam_appid = appid
            self._app.protondb_tier = tier
            self._app.protondb_fetched_at = now
        except Exception:
            pass  # DB update is best-effort — don't block the UI

        self._populate_summary(appid, summary)
        self._populate_tweaks(tweaks)
        self._populate_reports(reports)
        self._stack.set_visible_child_name("results")

    # ------------------------------------------------------------------
    # Populate UI
    # ------------------------------------------------------------------

    def _populate_summary(self, appid: int, summary: dict | None) -> None:
        while (child := self._summary_box.get_first_child()) is not None:
            self._summary_box.remove(child)

        tier = ""
        total = 0
        confidence = ""
        if isinstance(summary, dict):
            tier = summary.get("tier", "") or ""
            total = summary.get("total") or 0
            confidence = summary.get("confidence", "") or ""

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name_lbl = Gtk.Label(
            label=f"<b>{GLib.markup_escape_text(self._app.name)}</b>  (appid {appid})",
            xalign=0,
            use_markup=True,
        )
        name_lbl.set_hexpand(True)
        row.append(name_lbl)

        tier_label = Gtk.Label(label=(tier.upper() if tier else "UNKNOWN"))
        tier_label.add_css_class("heading")
        color_class = _TIER_COLORS.get(tier.lower(), "")
        if color_class:
            tier_label.add_css_class(color_class)
        row.append(tier_label)
        self._summary_box.append(row)

        if total:
            sub = Gtk.Label(
                label=f"{total} report(s) · confidence: {confidence or 'n/a'}",
                xalign=0,
            )
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            self._summary_box.append(sub)

    def _populate_tweaks(self, tweaks: ProtonTweaks) -> None:
        for row in self._tweak_rows:
            self._tweaks_group.remove(row)
        self._tweak_rows = []
        self._tweak_checks = {}

        if tweaks.is_empty():
            row = Adw.ActionRow(
                title="No tweaks detected",
                subtitle="Reports didn't include parseable launch options.",
            )
            self._tweaks_group.add(row)
            self._tweak_rows.append(row)
            self._apply_btn.set_sensitive(False)
            return

        self._apply_btn.set_sensitive(True)

        current = self._app_config
        for arg in tweaks.launch_args:
            already = arg in current.launch_args
            self._add_tweak_row(
                key=f"launch:{arg}",
                title=f"Launch arg: {arg}",
                subtitle="Already set" if already else None,
                active=not already,
            )
        for key, val in tweaks.env.items():
            already = current.env.get(key) == val
            self._add_tweak_row(
                key=f"env:{key}",
                title=f"Env: {key}={val}",
                subtitle="Already set" if already else None,
                active=not already,
            )
        for verb in tweaks.verbs:
            already = verb in current.winetricks_verbs
            self._add_tweak_row(
                key=f"verb:{verb}",
                title=f"Winetricks verb: {verb}",
                subtitle="Already applied" if already else None,
                active=not already,
            )
        for dll, mode in tweaks.dll_overrides.items():
            already = current.dll_overrides.get(dll) == mode
            self._add_tweak_row(
                key=f"dll:{dll}",
                title=f"DLL override: {dll}={mode}",
                subtitle="Already set" if already else None,
                active=not already,
            )

    def _add_tweak_row(self, *, key: str, title: str, subtitle: str | None, active: bool) -> None:
        row = Adw.ActionRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        check.set_active(active)
        row.add_prefix(check)
        row.set_activatable_widget(check)
        self._tweaks_group.add(row)
        self._tweak_rows.append(row)
        self._tweak_checks[key] = check

    def _populate_reports(self, reports: list[dict]) -> None:
        while (child := self._reports_list.get_first_child()) is not None:
            self._reports_list.remove(child)
        if not reports:
            row = Adw.ActionRow(title="No reports available")
            self._reports_list.append(row)
            return
        for r in reports[:5]:
            title_bits = []
            if r.get("rating") or r.get("tier"):
                title_bits.append(str(r.get("rating") or r.get("tier")).title())
            if r.get("protonVersion"):
                title_bits.append(f"Proton {r['protonVersion']}")
            if r.get("timestamp"):
                title_bits.append(str(r["timestamp"])[:10])
            title = " · ".join(title_bits) or "Report"
            body = _truncate(self._report_body_for_display(r), 220)
            row = Adw.ActionRow(title=title, subtitle=body)
            self._reports_list.append(row)

    def _report_body_for_display(self, report: dict) -> str:
        for key in ("notes", "body", "comment", "text"):
            val = report.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return "(no notes)"

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _on_apply_clicked(self, _btn: Gtk.Button) -> None:
        cfg = self._app_config
        launch_args = list(cfg.launch_args)
        env = dict(cfg.env)
        verbs = list(cfg.winetricks_verbs)
        dll = dict(cfg.dll_overrides)

        for key, check in self._tweak_checks.items():
            if not check.get_active():
                continue
            kind, _, payload = key.partition(":")
            if kind == "launch" and payload not in launch_args:
                launch_args.append(payload)
            elif kind == "env":
                env_val = self._tweaks.env.get(payload)
                if env_val is not None:
                    env[payload] = env_val
            elif kind == "verb" and payload not in verbs:
                verbs.append(payload)
            elif kind == "dll":
                mode = self._tweaks.dll_overrides.get(payload)
                if mode:
                    dll[payload] = mode

        updated = replace(
            cfg,
            launch_args=launch_args,
            env=env,
            winetricks_verbs=verbs,
            dll_overrides=dll,
        )
        save_app_config(self._app.app_id, self._config, updated)
        if self._on_config_saved:
            self._on_config_saved(updated)
        if self._on_toast:
            self._on_toast("ProtonDB tweaks applied")
        self._stack.set_visible_child_name("done")


def _truncate(text: str, limit: int) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"
