# exwin Roadmap

**exwin** is an offline-first Windows software/game manager for Linux. It provides a Steam-like GUI experience for browsing, installing, and launching Windows applications via Proton/Wine, with first-class automation support for GOG offline installers.

---

## Goals

1. **GUI** — Browse, launch, install, and uninstall applications from a unified library view.
2. **Proton/Wine Backend** — Per-app configuration management for Proton/Wine environments (prefixes, versions, overrides, tricks).
3. **GOG Automation Workflow** — End-to-end automation: select a GOG offline installer → extract/install → configure → appear as launchable entry in the library.

---

## Milestone 0 — Project Foundation

- [x] Choose GUI framework: **GTK4 + libadwaita (Python)**
- [x] Choose backend language: **Python**
- [x] Choose database: **SQLite** (via Python `sqlite3` stdlib)
- [x] Define app data model (library entries, per-app config schema)
- [x] Define storage layout (`~/.local/share/exwin/` — see Architecture Notes)
- [x] Set up project scaffold (`pyproject.toml`, venv with `--system-site-packages`, `ruff`, entry point)
- [x] Design SQLite schema (`apps` and `runtimes` tables, WAL mode, FK enforcement)
- [x] Per-app supplemental config format: **TOML** (via `tomllib`/`tomli-w`)

---

## Milestone 1 — Core GUI (Library Shell)

Goal: A working window that can display a list of apps and supports basic actions.

### 1.1 Library View
- [x] Grid/list view of installed applications (`Gtk.FlowBox` of `_AppCard` widgets)
- [x] App cards with: name, cover art/icon, source badge
- [x] Search and filter (by name, live with `FlowBox.set_filter_func`)
- [x] Sidebar navigation (`Gtk.ListBox` with `navigation-sidebar` style; Library + Settings)

### 1.2 App Detail View
- [x] App info panel (name, description, paths, dates) — `AppDetailDialog` (`AdwDialog`)
- [x] Launch / Stop controls (stub → toast; real impl M2)
- [x] Uninstall button (deletes from DB + refreshes library)
- [x] Open prefix directory shortcut (`xdg-open`)

### 1.3 Settings / Preferences
- [x] Default Wine/Proton version display (placeholder row)
- [x] Default install root directory display + open button
- [x] Theme (dark/light/system) via `Adw.StyleManager` + `AdwComboRow`

### 1.4 Notifications & Status
- [x] In-app toast notifications via `AdwToastOverlay` + `AdwToast`
- [x] Taskbar/tray icon (via StatusNotifierItem/DBus — no extra C library)

---

## Milestone 2 — Proton/Wine Backend

Goal: Reliable, isolated, per-app Wine environments with configurable Proton/Wine versions.

### 2.1 Runtime Management
- [x] Detect installed Proton versions (scans `~/.steam/root/steamapps/common/`, `compatibilitytools.d/`)
- [x] Detect system Wine via `which wine`
- [x] Persist detected runtimes to DB (`sync_runtimes` upserts on every startup)
- [x] Runtimes listed in Settings page; first detected runtime used as default
- [x] Support downloading/updating Proton-GE versions (M4)

### 2.2 Prefix Management
- [x] Create isolated prefix root per app (`~/.local/share/exwin/prefixes/<app-id>/`)
- [x] Initialize Wine prefix via `wineboot --init` (Wine); Proton self-initialises on first run
- [x] `wineprefix_path()` returns correct path for runtime type (Proton: `pfx/` subdir; Wine: root)
- [x] Delete prefix on uninstall (`delete_prefix` + `shutil.rmtree`)

### 2.3 Winetricks Integration
- [x] `run_verbs(prefix_root, verbs, runtime)` spawns winetricks with correct WINEPREFIX
- [x] Proton bundled wine binaries used when available (WINE/WINESERVER env vars)
- [x] Per-app verb list stored in `app.toml` under `[wine] winetricks_verbs`
- [x] GUI for managing winetricks deps per app (M4 polish)

### 2.4 Per-App Configuration
- [x] `AppConfig` dataclass + TOML round-trip (`apps/<app-id>/app.toml`)
- [x] Environment variable overrides (`[env]` section)
- [x] Launch arguments, Gamemode, Mangohud toggles (`[launch]` section)
- [x] Wine DLL overrides (`[dll_overrides]` → `WINEDLLOVERRIDES`)
- [x] Wine arch selection (`win32` / `win64`)
- [x] DXVK / VKD3D-Proton auto-install into prefix (M4)

### 2.5 Launch Pipeline
- [x] `Launcher.launch()` — resolves runtime → builds env/command → spawns process
- [x] `STEAM_COMPAT_DATA_PATH` + `STEAM_COMPAT_CLIENT_INSTALL_PATH` set for Proton
- [x] stdout/stderr captured to `logs/<app-id>.log`
- [x] Running state tracked in `Launcher._running` dict; `running_ids()` exposed
- [x] Running badge (▶) shown on library cards; detail dialog shows Stop button
- [x] `Launcher.stop()` sends SIGTERM; daemon thread calls `GLib.idle_add` on exit
- [x] `last_launched` timestamp updated in DB on process exit

---

## Milestone 3 — GOG Offline Installer Automation

Goal: A user selects a GOG offline installer (`.exe` or multi-part set) and exwin handles everything, resulting in a launchable library entry.

### 3.1 Installer Detection & Validation
- [x] Accept single `.exe` GOG installers (multi-part `.bin` handled natively by innoextract)
- [x] `probe()` — runs `innoextract --info`, parses title / GOG ID / setup version / languages
- [x] Stable `app_id` derived from GOG game ID: `gog-<game_id>`
- [x] Checksum validation (GOG `.hashdb` sidecar — MD5 per-part, step 0 of install)

### 3.2 Extraction / Installation
- [x] `extract()` — runs `innoextract --extract`, streams output to progress callback
- [x] Files extracted directly to `apps/<app-id>/` — no intermediate staging copy
- [x] `goggame-<id>.info` and `goggame-<id>.hashdb` preserved in install dir for reference
- [x] Wine fallback for installers that require it (M4)

### 3.3 Post-Install Configuration
- [x] `find_primary_exe()` — reads `playTasks[].isPrimary` from `goggame-*.info`
- [x] `guess_exe()` — heuristic fallback: skips `__redist/`, matches title to exe stem
- [x] `find_cover_art()` — picks smallest `*_english.jpg` from `tmp/` (GOG portrait cover art)
- [x] Cover art copied to `metadata/<app-id>/cover.jpg`
- [x] Winetricks verbs applied post-extraction (user-entered in install dialog)
- [x] Per-app `app.toml` written with arch + verb list
- [x] GOG API metadata fetch (M4)

### 3.4 App Config Database (Community / Local)
- [x] Per-app TOML at `apps/<app-id>/app.toml` (from M2) — winetricks deps, env vars, launch args
- [ ] Community compatibility database (M4)

### 3.5 Uninstall
- [x] `delete_app()` removes DB entry
- [x] `delete_prefix()` removes `prefixes/<app-id>/` tree
- [x] `shutil.rmtree(install_path)` removes game files (called in `_uninstall_app`)
- [x] Metadata cache cleanup (cover art + app config dir removed on uninstall)
- [ ] Save game preservation heuristics (M4)

---

## Milestone 4 — Polish & Extensibility

- [x] Support non-GOG Windows installers (Wine-direct interactive flow + exe selection)
- [x] DXVK / VKD3D-Proton auto-install into prefix (toggles in install dialog + app settings)
- [x] Proton-GE download from GitHub releases (Settings → Download… → progress dialog)
- [x] Winetricks GUI per app (App Settings dialog with verb entry + Apply Now button)
- [x] GOG API metadata fetch post-install (description + cover art from api.gog.com)
- [x] App config editor UI (AppSettingsDialog: exe, arch, env vars, DLL overrides, launch opts)
- [ ] Import existing Lutris / Heroic / bottles configurations
- [ ] Controller support / gamepad navigation in GUI
- [x] Flatpak packaging (v0.1.0)
- [ ] Plugin/hook system for custom pre/post install scripts
- [x] Automatic save game backup (M8 — backup/restore buttons in AppDetailDialog + CLI)

---

## Architecture Notes

### Stack
| Layer | Choice |
|---|---|
| GUI | GTK4 + libadwaita (Python, via `PyGObject`) |
| Backend/Core | Python 3.11+ |
| Database | SQLite (stdlib `sqlite3`) for library; TOML for per-app config |
| Installer parsing | `innoextract` (GOG/InnoSetup), `cabextract`, `7z` |
| Wine runtime | Proton-GE, system Wine, managed via exwin |
| DX translation | DXVK, VKD3D-Proton (auto-installed into prefix) |
| Async/subprocess | `asyncio` + `subprocess` / `GLib.spawn_async` for non-blocking ops |

### Disk Layout (proposed)
```
~/.local/share/exwin/
├── library.db              # SQLite library database
├── config.toml             # Global config (TOML)
├── prefixes/
│   └── <app-id>/           # Per-app Wine prefix (WINEPREFIX)
├── apps/
│   └── <app-id>/           # Installed app files (drive_c contents or symlink)
│       └── app.toml        # Per-app config (exe path, winetricks deps, env vars, etc.)
├── runtimes/
│   └── proton-ge-9.x/      # Downloaded Proton/Wine runtimes
├── metadata/
│   └── <app-id>/
│       ├── cover.jpg       # Cover art
│       └── meta.toml       # Title, description, tags, source (GOG, etc.)
└── logs/
    └── <app-id>.log        # Per-app launch logs
```

### GOG Install Flow (detailed)
```
User selects installer file(s)
        │
        ▼
Detect & validate (innoextract --info)
        │
        ▼
Create Wine prefix  ──────────────────────────────────────────┐
        │                                                     │
        ▼                                                     │
Extract via innoextract (preferred)                           │
  or run installer via Wine (fallback)                       │
        │                                                     │
        ▼                                                     │
Relocate files to prefix drive_c/                            │
        │                                                     │
        ▼                                                     │
Apply winetricks deps (from app config or user input) ────────┘
        │
        ▼
Detect main executable
        │
        ▼
Fetch metadata (title, art, description)
        │
        ▼
Write library entry → app appears in GUI
```

---

## Open Questions

- Whether to bundle Proton-GE or require users to have Steam/GE-Proton installed
- Community compatibility database hosting (self-hosted, GitHub-backed, or local-only MVP)
- Save game detection heuristics per game
- Handling multi-disc / multi-part GOG installers seamlessly
- GLib main loop integration strategy for async subprocess output (GLib.IOChannel vs asyncio bridge)
