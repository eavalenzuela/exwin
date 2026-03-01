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
- [ ] Grid/list view of installed applications
- [ ] App cards with: name, cover art/icon, play button, install status badge
- [ ] Search and filter (by name, tag, install status)
- [ ] Sidebar or top-bar navigation

### 1.2 App Detail View
- [ ] App info panel (name, description, size on disk, Wine/Proton version in use)
- [ ] Launch / Stop controls
- [ ] Uninstall button
- [ ] Open prefix directory shortcut

### 1.3 Settings / Preferences
- [ ] Default Wine/Proton version selector
- [ ] Default install root directory
- [ ] Theme (dark/light)

### 1.4 Notifications & Status
- [ ] In-app notification area for install progress, errors, launch events
- [ ] Taskbar/tray icon (optional, post-MVP)

---

## Milestone 2 — Proton/Wine Backend

Goal: Reliable, isolated, per-app Wine environments with configurable Proton/Wine versions.

### 2.1 Runtime Management
- [ ] Detect installed Proton versions (from Steam compatibilitytools.d, GE-Proton, system Wine)
- [ ] Support downloading/updating Proton-GE versions
- [ ] Select per-app runtime (Proton version or system Wine)

### 2.2 Prefix Management
- [ ] Create isolated Wine prefixes per application (stored under a configurable root, e.g. `~/.local/share/exwin/prefixes/<app-id>/`)
- [ ] Initialize prefixes (WINEPREFIX setup, arch selection: win32/win64)
- [ ] Delete prefix on uninstall

### 2.3 Winetricks Integration
- [ ] Run winetricks verbs against a specific prefix
- [ ] Per-app winetricks dependency list (stored in app config, applied automatically at install time)
- [ ] Common verb presets (vcredist, dotnet, dxvk, vkd3d, etc.)

### 2.4 Per-App Configuration
- [ ] Environment variable overrides (DXVK, VKD3D-Proton flags, WINE_*, etc.)
- [ ] Launch arguments / pre-launch scripts
- [ ] DXVK / VKD3D-Proton version selection and auto-install into prefix
- [ ] Wine DLL overrides
- [ ] Gamemode / Mangohud toggles

### 2.5 Launch Pipeline
- [ ] Resolve runtime → build environment → exec target executable
- [ ] Capture stdout/stderr to a per-app log file
- [ ] Track running state (PID watching, "running" badge in GUI)
- [ ] Kill / force-stop running app

---

## Milestone 3 — GOG Offline Installer Automation

Goal: A user selects a GOG offline installer (`.exe` or multi-part set) and exwin handles everything, resulting in a launchable library entry.

### 3.1 Installer Detection & Validation
- [ ] Accept single `.exe` or multi-part GOG installers (`.exe` + `.bin` parts)
- [ ] Parse GOG installer metadata (game title, version, language) from the installer binary (InnoSetup extraction via `innoextract`)
- [ ] Validate file integrity (checksums if available)

### 3.2 Extraction / Installation
- [ ] Use `innoextract` to extract GOG installer contents to a staging directory
- [ ] Alternatively, run the GOG installer via Wine in a controlled prefix (for installers that require it)
- [ ] Detect and relocate installed files to the app's prefix `drive_c/` directory
- [ ] Record installed file manifest for clean uninstall

### 3.3 Post-Install Configuration
- [ ] Auto-detect main executable (heuristics: GOG game info files, `*.exe` search, user confirmation fallback)
- [ ] Apply any required winetricks verbs (user-configurable or from a community config database)
- [ ] Create library entry with metadata (title, cover art from GOG CDN or local cache, description)
- [ ] Fetch cover art / metadata from IGDB, GOG API (public), or allow manual override

### 3.4 App Config Database (Community / Local)
- [ ] Local config file per app (TOML or YAML): winetricks deps, env vars, launch args, known working Proton version
- [ ] Optional: community-maintained compatibility database (similar to ProtonDB) bundled or fetched at runtime
- [ ] User can override any field locally

### 3.5 Uninstall
- [ ] Remove app files (installed directory)
- [ ] Delete Wine prefix
- [ ] Remove library entry and metadata cache
- [ ] Optionally retain user save data (detect and preserve common save locations)

---

## Milestone 4 — Polish & Extensibility

- [ ] Support non-GOG Windows installers (generic `.exe` / NSIS / MSI install-via-Wine flow)
- [ ] Import existing Lutris / Heroic / bottles configurations
- [ ] Controller support / gamepad navigation in GUI
- [ ] Flatpak / AppImage packaging
- [ ] Plugin/hook system for custom pre/post install scripts
- [ ] Automatic save game backup

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
