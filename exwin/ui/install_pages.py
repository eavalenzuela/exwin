"""Page builder functions for the install dialog.

Each function creates a page widget, adds it to a Gtk.Stack, and returns
a namespace (SimpleNamespace) containing references to the widgets the
caller needs to interact with.
"""

from __future__ import annotations

from types import SimpleNamespace

from gi.repository import Adw, Gtk

from exwin.backend.gog_installer import find_innoextract
from exwin.backend.runtime import Runtime
from exwin.backend.winetricks import is_available as winetricks_available
from exwin.models import AppEntry
from exwin.ui.winetricks_picker import WinetricksRow

_ARCH_OPTIONS = ["win64", "win32"]


def build_welcome_page(
    stack: Gtk.Stack,
    on_choose_clicked,
) -> SimpleNamespace:
    """Build the initial 'Choose Installer' page."""
    page = Adw.StatusPage(
        title="Install a Game",
        description="Select a Windows installer (.exe, .msi) or archive (.zip, .7z, .rar).",
        icon_name="document-open-symbolic",
    )
    btn = Gtk.Button(label="Choose Installer…")
    btn.add_css_class("suggested-action")
    btn.add_css_class("pill")
    btn.connect("clicked", on_choose_clicked)
    page.set_child(btn)

    try:
        find_innoextract()
    except RuntimeError as exc:
        warn = Gtk.Label(label=str(exc))
        warn.add_css_class("error")
        warn.set_wrap(True)
        warn.set_halign(Gtk.Align.CENTER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_halign(Gtk.Align.CENTER)
        box.append(btn)
        box.append(warn)
        page.set_child(box)

    stack.add_named(page, "welcome")
    return SimpleNamespace()


def build_confirm_gog_page(
    stack: Gtk.Stack,
    runtimes: list[Runtime],
    base_games: list[AppEntry],
    on_install_clicked,
    on_gog_wine_toggled,
    on_dlc_toggled,
) -> SimpleNamespace:
    """Build the GOG/InnoSetup confirmation page.

    Returns a namespace with: rar_warn_banner, title_row, gameid_row,
    lang_row, parts_row, runtime_row, arch_row, winetricks_row,
    dlc_switch_row, base_game_row, dxvk_row, vkd3d_row, gog_wine_row,
    install_btn.
    """
    scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

    box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=16,
        margin_top=16,
        margin_bottom=16,
        margin_start=16,
        margin_end=16,
    )
    scroll.set_child(box)

    rar_warn_banner = Adw.Banner(
        title="Multi-part installer requires 'unrar' or 'unar' — install one to continue.",
        revealed=False,
    )
    box.append(rar_warn_banner)

    game_info_group = Adw.PreferencesGroup(title="Game")
    title_row = Adw.ActionRow(title="Title")
    gameid_row = Adw.ActionRow(title="GOG ID")
    lang_row = Adw.ActionRow(title="Languages")
    parts_row = Adw.ActionRow(title="Installer Parts")
    game_info_group.add(title_row)
    game_info_group.add(gameid_row)
    game_info_group.add(lang_row)
    game_info_group.add(parts_row)
    box.append(game_info_group)

    options_group = Adw.PreferencesGroup(title="Install Options")
    box.append(options_group)

    runtime_row = Adw.ComboRow(title="Runtime")
    rt_names = [rt.name for rt in runtimes] if runtimes else ["None detected"]
    runtime_row.set_model(Gtk.StringList.new(rt_names))
    runtime_row.set_selected(0)
    options_group.add(runtime_row)

    arch_row = Adw.ComboRow(title="Windows Architecture")
    arch_row.set_model(Gtk.StringList.new(_ARCH_OPTIONS))
    arch_row.set_selected(0)
    options_group.add(arch_row)

    winetricks_row = WinetricksRow(title="Winetricks Verbs")
    winetricks_row.set_tooltip_text("Pick verbs to apply (e.g. vcrun2019, dxvk)")
    if not winetricks_available():
        winetricks_row.set_sensitive(False)
        winetricks_row.set_title("Winetricks Verbs (winetricks not installed)")
    options_group.add(winetricks_row)

    dlc_switch_row = Adw.SwitchRow(
        title="DLC / Add-on",
        subtitle="Install into an existing game's directory",
    )
    if not base_games:
        dlc_switch_row.set_sensitive(False)
        dlc_switch_row.set_subtitle("No games installed yet")
    dlc_switch_row.connect("notify::active", on_dlc_toggled)
    options_group.add(dlc_switch_row)

    base_names = [app.name for app in base_games] or ["—"]
    base_game_row = Adw.ComboRow(title="Base Game")
    base_game_row.set_model(Gtk.StringList.new(base_names))
    base_game_row.set_selected(0)
    base_game_row.set_visible(False)
    options_group.add(base_game_row)

    dxvk_row = Adw.SwitchRow(title="Install DXVK", subtitle="DirectX 9/10/11 → Vulkan")
    options_group.add(dxvk_row)

    vkd3d_row = Adw.SwitchRow(title="Install VKD3D-Proton", subtitle="DirectX 12 → Vulkan")
    options_group.add(vkd3d_row)

    gog_wine_row = Adw.SwitchRow(
        title="Run via Wine Installer",
        subtitle="Runs the GOG setup interactively — required for games that use registry-based CD keys",
    )
    gog_wine_row.connect("notify::active", on_gog_wine_toggled)
    options_group.add(gog_wine_row)

    install_btn = Gtk.Button(label="Install")
    install_btn.add_css_class("suggested-action")
    install_btn.add_css_class("pill")
    install_btn.set_halign(Gtk.Align.CENTER)
    install_btn.connect("clicked", on_install_clicked)
    box.append(install_btn)

    stack.add_named(scroll, "confirm")

    return SimpleNamespace(
        rar_warn_banner=rar_warn_banner,
        title_row=title_row,
        gameid_row=gameid_row,
        lang_row=lang_row,
        parts_row=parts_row,
        runtime_row=runtime_row,
        arch_row=arch_row,
        winetricks_row=winetricks_row,
        dlc_switch_row=dlc_switch_row,
        base_game_row=base_game_row,
        dxvk_row=dxvk_row,
        vkd3d_row=vkd3d_row,
        gog_wine_row=gog_wine_row,
        install_btn=install_btn,
    )


def build_confirm_generic_page(
    stack: Gtk.Stack,
    runtimes: list[Runtime],
    base_games: list[AppEntry],
    on_install_clicked,
    on_dlc_toggled,
) -> SimpleNamespace:
    """Build the generic (Wine) installer confirmation page.

    Returns a namespace with: file_row, runtime_row, arch_row,
    winetricks_row, dlc_switch_row, base_game_row, dxvk_row, vkd3d_row.
    """
    scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

    box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=16,
        margin_top=16,
        margin_bottom=16,
        margin_start=16,
        margin_end=16,
    )
    scroll.set_child(box)

    info_group = Adw.PreferencesGroup(title="Installer")
    file_row = Adw.ActionRow(title="File")
    info_group.add(file_row)
    box.append(info_group)

    banner = Gtk.Label(
        label="This installer will run interactively via Wine.\n"
        "Interact with the Windows installer window to complete installation.",
        wrap=True,
        halign=Gtk.Align.CENTER,
    )
    banner.add_css_class("dim-label")
    banner.add_css_class("caption")
    box.append(banner)

    options_group = Adw.PreferencesGroup(title="Install Options")
    box.append(options_group)

    runtime_row = Adw.ComboRow(title="Runtime")
    rt_names = [rt.name for rt in runtimes] if runtimes else ["None detected"]
    runtime_row.set_model(Gtk.StringList.new(rt_names))
    runtime_row.set_selected(0)
    options_group.add(runtime_row)

    arch_row = Adw.ComboRow(title="Windows Architecture")
    arch_row.set_model(Gtk.StringList.new(_ARCH_OPTIONS))
    arch_row.set_selected(0)
    options_group.add(arch_row)

    winetricks_row = WinetricksRow(title="Winetricks Verbs (post-install)")
    winetricks_row.set_tooltip_text("Applied after installation completes")
    if not winetricks_available():
        winetricks_row.set_sensitive(False)
        winetricks_row.set_title("Winetricks Verbs (winetricks not installed)")
    options_group.add(winetricks_row)

    dlc_switch_row = Adw.SwitchRow(
        title="DLC / Add-on",
        subtitle="Install into an existing game's directory",
    )
    if not base_games:
        dlc_switch_row.set_sensitive(False)
        dlc_switch_row.set_subtitle("No games installed yet")
    dlc_switch_row.connect("notify::active", on_dlc_toggled)
    options_group.add(dlc_switch_row)

    base_names = [app.name for app in base_games] or ["—"]
    base_game_row = Adw.ComboRow(title="Base Game")
    base_game_row.set_model(Gtk.StringList.new(base_names))
    base_game_row.set_selected(0)
    base_game_row.set_visible(False)
    options_group.add(base_game_row)

    install_dir_row = Adw.EntryRow(title="Run From Folder")
    install_dir_row.set_tooltip_text(
        "The installer is copied into this folder and run there, so patch and "
        "add-on installers that look for the game next to their own .exe find it. "
        "Defaults to the base game's install folder."
    )
    install_dir_browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
    install_dir_browse.add_css_class("flat")
    install_dir_row.add_suffix(install_dir_browse)
    install_dir_row.set_visible(False)
    options_group.add(install_dir_row)

    dxvk_row = Adw.SwitchRow(title="Install DXVK", subtitle="DirectX 9/10/11 → Vulkan")
    options_group.add(dxvk_row)

    vkd3d_row = Adw.SwitchRow(title="Install VKD3D-Proton", subtitle="DirectX 12 → Vulkan")
    options_group.add(vkd3d_row)

    install_btn = Gtk.Button(label="Run Installer")
    install_btn.add_css_class("suggested-action")
    install_btn.add_css_class("pill")
    install_btn.set_halign(Gtk.Align.CENTER)
    install_btn.connect("clicked", on_install_clicked)
    box.append(install_btn)

    stack.add_named(scroll, "confirm_generic")

    return SimpleNamespace(
        file_row=file_row,
        runtime_row=runtime_row,
        arch_row=arch_row,
        winetricks_row=winetricks_row,
        dlc_switch_row=dlc_switch_row,
        base_game_row=base_game_row,
        install_dir_row=install_dir_row,
        install_dir_browse=install_dir_browse,
        dxvk_row=dxvk_row,
        vkd3d_row=vkd3d_row,
    )


def build_confirm_archive_page(
    stack: Gtk.Stack,
    runtimes: list[Runtime],
    on_install_clicked,
) -> SimpleNamespace:
    """Build the archive (zip/7z/rar) confirmation page.

    Returns a namespace with: file_row, name_row, runtime_row, arch_row,
    winetricks_row, dxvk_row, vkd3d_row, tool_warn_banner, install_btn.
    """
    scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

    box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=16,
        margin_top=16,
        margin_bottom=16,
        margin_start=16,
        margin_end=16,
    )
    scroll.set_child(box)

    tool_warn_banner = Adw.Banner(title="", revealed=False)
    box.append(tool_warn_banner)

    info_group = Adw.PreferencesGroup(title="Archive")
    file_row = Adw.ActionRow(title="File")
    info_group.add(file_row)

    name_row = Adw.EntryRow(title="Name")
    name_row.set_tooltip_text("Display name — also used to derive the install directory.")
    info_group.add(name_row)
    box.append(info_group)

    hint = Gtk.Label(
        label="The archive will be extracted directly — no Windows installer runs.",
        wrap=True,
        halign=Gtk.Align.CENTER,
    )
    hint.add_css_class("dim-label")
    hint.add_css_class("caption")
    box.append(hint)

    options_group = Adw.PreferencesGroup(title="Runtime Options")
    box.append(options_group)

    runtime_row = Adw.ComboRow(title="Runtime")
    rt_names = [rt.name for rt in runtimes] if runtimes else ["None detected"]
    runtime_row.set_model(Gtk.StringList.new(rt_names))
    runtime_row.set_selected(0)
    options_group.add(runtime_row)

    arch_row = Adw.ComboRow(title="Windows Architecture")
    arch_row.set_model(Gtk.StringList.new(_ARCH_OPTIONS))
    arch_row.set_selected(0)
    options_group.add(arch_row)

    winetricks_row = WinetricksRow(title="Winetricks Verbs")
    winetricks_row.set_tooltip_text("Pick verbs to apply (e.g. vcrun2019, corefonts)")
    if not winetricks_available():
        winetricks_row.set_sensitive(False)
        winetricks_row.set_title("Winetricks Verbs (winetricks not installed)")
    options_group.add(winetricks_row)

    dxvk_row = Adw.SwitchRow(title="Install DXVK", subtitle="DirectX 9/10/11 → Vulkan")
    options_group.add(dxvk_row)

    vkd3d_row = Adw.SwitchRow(title="Install VKD3D-Proton", subtitle="DirectX 12 → Vulkan")
    options_group.add(vkd3d_row)

    install_btn = Gtk.Button(label="Extract & Install")
    install_btn.add_css_class("suggested-action")
    install_btn.add_css_class("pill")
    install_btn.set_halign(Gtk.Align.CENTER)
    install_btn.connect("clicked", on_install_clicked)
    box.append(install_btn)

    stack.add_named(scroll, "confirm_archive")

    return SimpleNamespace(
        file_row=file_row,
        name_row=name_row,
        runtime_row=runtime_row,
        arch_row=arch_row,
        winetricks_row=winetricks_row,
        dxvk_row=dxvk_row,
        vkd3d_row=vkd3d_row,
        tool_warn_banner=tool_warn_banner,
        install_btn=install_btn,
    )


def build_installing_page(stack: Gtk.Stack) -> SimpleNamespace:
    """Build the progress/log page shown during extraction.

    Returns a namespace with: spinner, status_label, progress_bar,
    log_buffer, log_scroll.
    """
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
    spinner = Gtk.Spinner()
    spinner.set_spinning(False)
    status_box.append(spinner)

    status_label = Gtk.Label(label="Installing…")
    status_label.add_css_class("heading")
    status_box.append(status_label)
    box.append(status_box)

    progress_bar = Gtk.ProgressBar()
    progress_bar.set_show_text(True)
    progress_bar.set_visible(False)
    box.append(progress_bar)

    scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

    log_buffer = Gtk.TextBuffer()
    log_view = Gtk.TextView(buffer=log_buffer, editable=False, monospace=True)
    log_view.add_css_class("caption")
    scroll.set_child(log_view)
    box.append(scroll)

    stack.add_named(box, "installing")

    return SimpleNamespace(
        spinner=spinner,
        status_label=status_label,
        progress_bar=progress_bar,
        log_buffer=log_buffer,
        log_scroll=scroll,
    )


def build_wine_running_page(stack: Gtk.Stack, on_cancel) -> SimpleNamespace:
    """Build the 'Installer Running' status page."""
    page = Adw.StatusPage(
        title="Installer Running",
        description="Interact with the Windows installer window.\n"
        "exwin will continue automatically when you close it.",
        icon_name="application-x-executable-symbolic",
    )
    cancel_btn = Gtk.Button(label="Cancel")
    cancel_btn.add_css_class("destructive-action")
    cancel_btn.add_css_class("pill")
    cancel_btn.connect("clicked", on_cancel)
    page.set_child(cancel_btn)
    stack.add_named(page, "wine_running")
    return SimpleNamespace()


def build_exe_select_page(
    stack: Gtk.Stack,
    on_exe_confirmed,
    on_exe_row_selected,
) -> SimpleNamespace:
    """Build the executable selection page.

    Returns a namespace with: exe_list, confirm_btn.
    """
    box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=16,
        margin_bottom=16,
        margin_start=16,
        margin_end=16,
        vexpand=True,
    )

    title = Gtk.Label(label="Select the main executable")
    title.add_css_class("title-3")
    title.set_halign(Gtk.Align.START)
    box.append(title)

    subtitle = Gtk.Label(label="Choose the .exe file that launches the game or application.")
    subtitle.add_css_class("dim-label")
    subtitle.set_wrap(True)
    subtitle.set_halign(Gtk.Align.START)
    box.append(subtitle)

    scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

    exe_list = Gtk.ListBox()
    exe_list.add_css_class("boxed-list")
    exe_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
    scroll.set_child(exe_list)
    box.append(scroll)

    confirm_btn = Gtk.Button(label="Use Selected Executable")
    confirm_btn.add_css_class("suggested-action")
    confirm_btn.add_css_class("pill")
    confirm_btn.set_halign(Gtk.Align.CENTER)
    confirm_btn.set_sensitive(False)
    confirm_btn.connect("clicked", on_exe_confirmed)
    box.append(confirm_btn)

    exe_list.connect("row-selected", on_exe_row_selected)

    stack.add_named(box, "exe_select")

    return SimpleNamespace(
        exe_list=exe_list,
        confirm_btn=confirm_btn,
    )


def build_redist_page(stack: Gtk.Stack, on_apply, on_skip) -> SimpleNamespace:
    """Build the redistributable-prereq picker page.

    Returns a namespace with: list_box, apply_btn, skip_btn, status_label.
    The caller populates ``list_box`` with check-row widgets after scanning.
    """
    box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=16,
        margin_bottom=16,
        margin_start=16,
        margin_end=16,
        vexpand=True,
    )

    title = Gtk.Label(label="Install Prerequisites")
    title.add_css_class("title-3")
    title.set_halign(Gtk.Align.START)
    box.append(title)

    subtitle = Gtk.Label(
        label="The game ships bundled runtimes that Steam normally auto-installs. "
        "Select which to apply to the prefix now.",
        wrap=True,
        xalign=0,
    )
    subtitle.add_css_class("dim-label")
    box.append(subtitle)

    scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    list_box = Gtk.ListBox()
    list_box.add_css_class("boxed-list")
    list_box.set_selection_mode(Gtk.SelectionMode.NONE)
    scroll.set_child(list_box)
    box.append(scroll)

    status_label = Gtk.Label(xalign=0, wrap=True)
    status_label.add_css_class("caption")
    status_label.add_css_class("dim-label")
    box.append(status_label)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER)
    skip_btn = Gtk.Button(label="Skip")
    skip_btn.add_css_class("pill")
    skip_btn.connect("clicked", on_skip)
    btn_box.append(skip_btn)

    apply_btn = Gtk.Button(label="Apply Selected")
    apply_btn.add_css_class("suggested-action")
    apply_btn.add_css_class("pill")
    apply_btn.connect("clicked", on_apply)
    btn_box.append(apply_btn)
    box.append(btn_box)

    stack.add_named(box, "redist")

    return SimpleNamespace(
        list_box=list_box,
        apply_btn=apply_btn,
        skip_btn=skip_btn,
        status_label=status_label,
    )


def build_done_page(stack: Gtk.Stack, on_close) -> SimpleNamespace:
    """Build the success page.

    Returns a namespace with: page (Adw.StatusPage).
    """
    page = Adw.StatusPage(
        title="Installed!",
        icon_name="emblem-ok-symbolic",
    )
    close_btn = Gtk.Button(label="Close")
    close_btn.add_css_class("pill")
    close_btn.connect("clicked", on_close)
    page.set_child(close_btn)
    stack.add_named(page, "done")
    return SimpleNamespace(page=page)


def build_error_page(stack: Gtk.Stack, on_retry, on_close) -> SimpleNamespace:
    """Build the error page.

    Returns a namespace with: page (Adw.StatusPage).
    """
    page = Adw.StatusPage(
        title="Installation Failed",
        icon_name="dialog-error-symbolic",
    )
    btn_box = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=8,
        halign=Gtk.Align.CENTER,
    )
    retry_btn = Gtk.Button(label="Try Again")
    retry_btn.add_css_class("pill")
    retry_btn.connect("clicked", on_retry)
    close_btn = Gtk.Button(label="Close")
    close_btn.add_css_class("destructive-action")
    close_btn.add_css_class("pill")
    close_btn.connect("clicked", on_close)
    btn_box.append(retry_btn)
    btn_box.append(close_btn)
    page.set_child(btn_box)
    stack.add_named(page, "error")
    return SimpleNamespace(page=page)
