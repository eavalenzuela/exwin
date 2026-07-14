# exwin

**v0.5.0**

Offline-first Windows software/game manager for Linux — "offline Steam" with a Proton/Wine backend and first-class GOG offline installer automation.

## Features

- **Auto-detection install route** — every installer is analysed up front (magic bytes, PE header, InnoSetup/NSIS/InstallShield markers, self-extracting RAR/7z payloads, multi-part volume sets) and a one-click install plan is proposed: best extraction method, runtime (newest Proton-GE preferred), prefix architecture, and translation layers, each with a stated reason; a "Configure Manually" escape hatch keeps the full per-route options
- **Auto-configure game settings** — one click in per-game settings inspects the installed game (engine markers, DirectX/VC-runtime DLLs referenced by the exe, bundled redists) and the host (GPUs, Vulkan driver, gamemode) then applies the recommended settings: NVAPI/DLSS on NVIDIA, discrete-GPU override on hybrid laptops, DXVK/VKD3D where needed, per-app shader cache, gamemode, and missing winetricks runtime verbs — with an explainable preview before anything is written
- **GOG installer automation** — probe, extract, and install GOG offline installers (single-part and multi-part RAR/InnoSetup layouts) with automatic executable detection
- **DLC installs** — install GOG DLC on top of an existing base-game prefix
- **Archive installers** — install games shipped as plain `.zip`, `.7z`, or `.rar` archives (itch.io, indies, abandonware), including self-extracting `.exe` archives and multi-part volume sets; auto-detect main exe after extraction
- **MSI installers** — run `.msi` installers via `wine msiexec /i`
- **Generic installer support** — run any Windows installer interactively via Wine, then select the resulting executable
- **Library management** — searchable grid view with cover art (search matches names and tags); per-game settings persisted to `~/.exwin/`
- **Proton & Wine support** — launch games via any Proton (including Proton-GE) or Wine runtime detected under `~/.steam/root/`
- **Proton-GE installer** — fetch and install the latest Proton-GE release from within the app
- **DXVK / VKD3D-Proton** — one-click install via winetricks or bundled setup scripts
- **Winetricks verb picker** — searchable, categorised picker with descriptions and curated presets; no more freeform verb guessing
- **Redistributable auto-scan** — scan installed games for bundled VC++, DirectX, OpenAL, PhysX, UE prereq, .NET installers and offer to run them or apply the equivalent winetricks verb
- **ProtonDB lookup** — opt-in online lookup of tier + top community reports for any library entry; one-click apply of parsed launch args, env vars, verbs, and DLL overrides (cached locally for 7 days)
- **Gamescope wrapper** — per-game gamescope compositor with FSR/NIS upscaling, HDR, frame cap, fullscreen, MangoApp overlay, and extra-args escape hatch
- **GPU selection** — per-game GPU override via `DRI_PRIME` / `DXVK_FILTER_DEVICE_NAME` on multi-GPU systems
- **umu-launcher integration** — route Proton launches through `umu-run` for canonical Steam-compat env + ProtonFixes per-game lookups; global and per-app toggles with graceful fallback when `umu-run` is missing
- **Pre/post-launch hooks** — curated toggles (mount ISO, kill background processes, suspend KDE compositor, CPU performance governor) plus a `/bin/sh` escape hatch for custom pre/post commands; state is reversed on exit and a non-zero pre-launch command aborts the launch
- **Crash / short-run detection** — short-lived non-zero exits surface a crash dialog with the log tail, runtime + prefix arch, and one-click access to the full log
- **Folder / portable-game import** — add an already-extracted Windows game by pointing at its folder; scans for candidate exes and registers it without re-installing
- **Prefix upgrade** — one-click `wineboot -u` to refresh system DLLs after switching runtimes, preserving installed winetricks verbs and user data
- **Custom cover art** — set cover art from a local image file or an image URL in per-game settings
- **GOG metadata fetch** — pull title, description, and cover art from the GOG products API
- **Sleep inhibit during play** — hold a `systemd-inhibit` idle/sleep inhibitor for the whole game session (global toggle)
- **Wine sync & driver knobs** — per-game ESYNC/FSYNC tri-state, NVAPI/DLSS passthrough, locale override for region-locked titles, per-app DXVK shader cache
- **CPU affinity** — per-game `taskset -c` core pinning for old titles that break on high core counts
- **`.lnk` shortcut resolution** — folder import parses Windows shortcut stubs and promotes their targets to the top of the exe candidate list
- **CLI** — `list`, `info`, `launch`, `remove`, `migrate`, `backup-saves`, `restore-saves`, `backups` subcommands; the CLI never loads GTK
- **Per-game configuration** — architecture (win32/win64), DXVK, VKD3D, ESYNC/FSYNC, NVAPI, locale, CPU affinity, winetricks verbs, gamemode, MangoHud, launch arguments, environment variables, DLL overrides, GPU override, gamescope, umu toggle, pre/post-launch hooks

## Requirements

- Python 3.11+, PyGObject, libadwaita 1.3+
- `innoextract` (≥ 1.9) — GOG/InnoSetup extraction; place at `~/.local/bin/innoextract` or on `$PATH`
- `unar` (apt: `universe`) — GOG multi-part RAR `.bin` extraction and `.rar` archive installers
- `p7zip-full` — optional, for `.7z` archive installers
- `winetricks` — optional, for DXVK/VKD3D and verb automation
- `gamescope` — optional, enables the per-game gamescope wrapper (HDR/FSR/NIS/frame cap)
- `umu-run` (umu-launcher) — optional, enables Proton launches via the canonical Steam-compat entry point with ProtonFixes per-game support
- `udisksctl` / `fuseiso` — optional, used by the "Mount disc image" pre-launch hook
- `powerprofilesctl` — optional, used by the "CPU performance governor" pre-launch hook
- `systemd-inhibit` — optional, enables the "prevent sleep during play" inhibitor
- `taskset` (util-linux) — optional, enables per-game CPU affinity
- Proton or Wine runtime installed and discoverable under `~/.steam/root/`

## Installation / Running

```bash
python -m venv --system-site-packages .venv   # system-site-packages needed for PyGObject
.venv/bin/pip install -e .
.venv/bin/python -m exwin
```

## Changelog

### v0.5.0 (2026-07-13)
- **Auto-detection install route** — `backend/auto_detect.py` analyses the chosen installer (archive magic bytes, PE header, InnoSetup/NSIS/InstallShield/Setup Factory stub markers, embedded SFX payloads, multi-part volume sets, innoextract probe) and builds an explainable `InstallPlan`: extraction method, runtime (newest Proton-GE preferred), prefix architecture, and DXVK/VKD3D defaults. The install dialog now lands on a one-click "Install Automatically" review page with a "Configure Manually…" escape hatch that pre-fills the existing per-route pages
- **Self-extracting archive support** — RAR/7z SFX `.exe` installers (including multi-part `name.part1.exe` + `name.partN.rar` sets) are detected via `detect_sfx_archive()` and extracted directly with unar/unrar/7z instead of running the Windows stub interactively
- **Auto-configure game settings** — `backend/auto_config.py` + an "Auto-Configure" button in per-app settings: inspects the installed game (engine markers, DirectX/VC-runtime DLL references in the exe, bundled redists) and the host (GPUs, Vulkan ICDs, gamemode), previews every recommended change with a reason, then applies them — NVAPI/DLSS on NVIDIA, discrete-GPU override on hybrid laptops, DXVK/VKD3D where needed under plain Wine, per-app shader cache, gamemode, missing `vcrun` verbs
- Generic install path now honours the DXVK / VKD3D switches (previously ignored)
- Generic installer waits for the prefix's wineserver to go idle before scanning — bootstrapper installers (Setup Factory, NSIS/InstallShield stubs) no longer report false "install failed"
- Games unpacked outside `drive_c` (multi-part RAR SFX, portable extractors) are found by a prefix-extras scan
- DLC "Run From Folder" — patch/add-on installers are copied into (and run from) the base game's exe folder so they can find the game
- Fixed exe scan excluding every candidate when the prefix path contains a skip token (e.g. "…-setup")
- Flatpak: `--socket=x11` granted so Proton games render on Wayland hosts
- **Sleep/idle inhibit during play** — launches are wrapped in `systemd-inhibit --what=idle:sleep` (global "Prevent sleep during play" toggle; skipped when systemd-inhibit is absent)
- **Wine sync / NVAPI / locale env knobs** — per-app ESYNC and FSYNC tri-states (`WINEESYNC`/`WINEFSYNC` on Wine, inverted `PROTON_NO_ESYNC`/`PROTON_NO_FSYNC` on Proton), NVAPI/DLSS passthrough (`PROTON_ENABLE_NVAPI` + `DXVK_ENABLE_NVAPI`), locale override (`LANG`/`LC_ALL`), and a per-app DXVK state cache under the prefix (`DXVK_STATE_CACHE_PATH`)
- **CPU affinity** — per-app `taskset -c <list>` wrapper with validated cpu-list entry in the settings dialog
- **CLI `info` + `backups`** — `exwin info <id>` prints paths/runtime/playtime/ProtonDB/config summary; `exwin backups <id>` lists save backups with timestamp and size
- **`.lnk` shortcut resolution** — `backend/lnk.py` parses [MS-SHLLINK] LocalBasePath/RelativePath; folder import promotes shortcut targets over size/depth heuristics
- Stop now signals the whole process group — stopping a Proton/umu/gamescope-wrapped game no longer leaves the game itself running
- Headless `exwin launch` applies pre/post-launch hooks (parity with the GUI)
- The CLI no longer imports GTK (`fmt_playtime` moved to `exwin/util.py`) — `exwin list` works on headless machines
- Corrupt `config.toml` no longer crashes startup; it is backed up to `config.toml.bad` and defaults are used
- Launch logs keep one previous generation as `<id>.log.1`
- Crash-dialog log tails read at most the final 64 KiB of the log
- Subcommands reject unrecognised arguments instead of silently ignoring typos like `--delete-file`
- Uninstalling a running game stops it first
- Library search also matches tags
- README: corrected default data dir (`~/.exwin/`, override with `EXWIN_DATA_DIR`)

### v0.4.0 (2026-04-18)
- Five launch/import features landed together:
  - **Crash / short-run detection** — `backend/crash_detect.py` builds a `CrashInfo` when a game exits non-zero under `Config.crash_threshold_seconds`; `ui/crash_dialog.py` surfaces the log tail, runtime, prefix arch, and a "View Log" button; user-initiated stops suppress the dialog
  - **Folder / portable-game import** — `backend/folder_import.py` scans a chosen directory for candidate exes (shared with the post-install picker), registers it as a `MANUAL` app with its own prefix; "Add Existing" flow in `ui/add_existing_dialog.py`
  - **Prefix upgrade** (`wineboot -u`) — `backend/prefix_tools.py` exposes `upgrade_prefix(prefix, runtime)`; "Upgrade Prefix" button in `ui/app_settings_dialog.py` runs it on a background thread with a 3-minute timeout and logs to `~/.exwin/logs/<id>-wineboot-u.log`
  - **Pre/post-launch hooks** — `backend/hooks.py` implements curated toggles (mount ISO via `udisksctl`/`fuseiso` fallback, `pkill -x` process kill list with validated names, KDE compositor suspend via qdbus, CPU performance governor via `powerprofilesctl`) plus a `/bin/sh -c` escape hatch; non-zero `pre_launch_cmd` aborts the launch by raising `HookAbort` (synthesised crash); post-hooks restore state even on abnormal exit; new Hooks group in `ui/app_settings_dialog.py`
  - **umu-launcher integration** — `backend/umu.py` detects `umu-run`; Proton launches route through `umu-run <exe>` with `GAMEID` (Steam AppID → ProtonFixes), `PROTONPATH`, `WINEPREFIX=<prefix>/pfx`; falls back to direct Proton when `umu-run` is absent or disabled; `Config.use_umu` (global, default on) and tri-state `AppConfig.use_umu` (Default / Force on / Force off) in Settings and per-app dialog
- Six install/launch features landed together:
  - **Archive installers** — `.zip`, `.7z`, `.rar` detected by magic bytes, extracted, auto-flattened if the archive has a single top-level directory; `backend/archive_installer.py`, shared exe heuristics in `backend/exe_filter.py`
  - **MSI installers** — `wine msiexec /i` path in `generic_installer.py`, unified through `run_installer()`; `.msi` added to the file picker
  - **Winetricks verb picker** — parsed catalog (`backend/winetricks_catalog.py`) with bundled fallback JSON, searchable per-category picker dialog (`ui/winetricks_picker.py`), replaces freeform entries in the install, add-existing, and settings dialogs
  - **Redist auto-scan** — pattern-based scan of freshly installed games (`backend/redist_scanner.py`), post-install page offers to run or map to equivalent winetricks verbs (`ui/redist_dialog.py`)
  - **Gamescope wrapper** — `GamescopeConfig` on `AppConfig` with TOML round-trip, launcher prefixes gamescope around Wine/Proton cmd, `gamescope --mangoapp` suppresses the outer MangoHud; new Gamescope settings group in `ui/app_settings_dialog.py`
  - **ProtonDB lookup** — opt-in online check via `store.steampowered.com` + `www.protondb.com` APIs (`backend/steam_appid.py`, `backend/protondb.py`), 7-day disk cache, tier + report dialog (`ui/protondb_dialog.py`) parses launch args / env / verbs / DLL overrides and applies them with a diff preview
  - DB additions: `steam_appid`, `protondb_tier`, `protondb_fetched_at` on `apps` (ALTER TABLE migrations in `schema.py`)
- Proton prefix init + "Rebuild Prefix" button (`prefix_tools.py`, `app_detail_dialog.py`)
- Debian package build via `packaging/deb/build-deb.sh`

### v0.3.0 (2026-03-24)
- Fix collapsed dialog issue — add `content_height` to AppDetailDialog, InstallDialog, AppSettingsDialog, and ProtonGEDialog
- Install dialog pages extracted to `install_pages.py` module
- Visual UI test scaffold (20 automated tests) validating dialog sizing, widget tree layout, and cross-dialog consistency
- Screenshot harness for automated visual regression testing under Xvfb

### v0.2.0 (2026-03-01)
- System tray icon via StatusNotifierItem (DBus) — close to tray, restore on click
- GOG installer checksum validation from `.hashdb` sidecar before extraction
- Play time tracking per game, displayed on library cards and detail view
- Save file backup and restore with per-app save path configuration
- CLI subcommands: `list`, `launch`, `remove`, `migrate`, `backup-saves`, `restore-saves`
- GPU selection per app (`DRI_PRIME` / `DXVK_FILTER_DEVICE_NAME`)
- Global storage root to redirect game files and prefixes to an external drive
- Metadata and config directory cleanup on uninstall

### v0.1.0 (2026-03-01)
- Initial release with full GOG offline installer automation, Proton/Wine backend, and GTK4/libadwaita UI

## Data layout

Default data directory is `~/.exwin/` (override with the `EXWIN_DATA_DIR`
environment variable; game files and prefixes can also be redirected to an
external drive via the `storage_root` setting).

```
~/.exwin/
├── library.db          # SQLite app registry
├── config.toml         # global config (data_dir, default runtime, etc.)
├── prefixes/<id>/      # Wine/Proton prefix roots
├── apps/<id>/          # install dirs + app.toml per-game config
├── metadata/<id>/      # cover art cache
├── runtimes/           # downloaded runtimes (Proton-GE, etc.)
├── saves/<id>/         # save backups (timestamped zips)
└── logs/
```
