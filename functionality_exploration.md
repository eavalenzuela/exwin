# Functionality Exploration — Installing and Running Games

This document enumerates features exwin is missing or under-implementing **specifically in the install-and-run pipeline**. Scope: installer coverage, Wine/Proton configuration and detection, per-app launch options, prefix management, diagnostics, runtime play experience. Library/UX features (tags, cloud sync, Big Picture, etc.) are out of scope here.

Each item is a candidate — not all are worth building. The companion `feature_implementation.md` picks six highest-leverage items and fleshes them out. **The six picked items have all shipped** (see bottom of this file and `feature_implementation.md`).

---

## 1. Installer format coverage

Today we handle: GOG `.exe` (InnoSetup + multi-part RAR via `innoextract --gog`), generic `.exe` via interactive Wine install, `.msi` via `wine msiexec /i`, and `.zip`/`.7z`/`.rar` archives via magic-byte detection + extraction.

| # | Feature | Notes |
|---|---|---|
| 1.1 | ZIP / 7z / RAR archive installers | **Shipped** (`backend/archive_installer.py`). |
| 1.2 | MSI installers | **Shipped** (`generic_installer.run_installer` with `kind="msi"`). |
| 1.3 | InstallShield CAB extraction | Needs `unshield`. At minimum, detect and emit an actionable error. |
| 1.4 | ISO / CUE / BIN disc images | Mount via `fuseiso` or udisks loop; treat mount as installer source. Classic CD-ROM games live here. |
| 1.5 | Multi-disc prompts | Detect "insert Disc 2" mid-install; offer a disc-swap dialog. |
| 1.6 | `.lnk` (Windows shortcut) resolution | Parse via `pylnk3` to pull real exe + working dir + args. GOG installers often leave `.lnk` stubs pointing at the true binary. |
| 1.7 | Self-extracting SFX `.exe` | Route 7z/WinRAR SFX through `unar` directly rather than running under Wine. |
| 1.8 | Folder / portable game import | "Point at a folder, auto-detect main exe, wrap it in a fresh prefix." Today: Add-Existing requires the user to specify the exe manually. |
| 1.9 | Batch / queued install | Pick N installers, walk the queue unattended. |
| 1.10 | Single-file `.exe` as a game | Portable freeware; no installer. Possible via Add-Existing but clumsy. |
| 1.11 | `.bat` launch target | Many mods / fan-patches ship a batch file as the real entry point. |

## 2. Wine/Proton configuration automation

Today: searchable winetricks verb picker with curated presets; DXVK/VKD3D toggles; opt-in ProtonDB lookup; redist auto-scan on install.

| # | Feature | Notes |
|---|---|---|
| 2.1 | ProtonDB lookup by app | **Shipped** (`backend/protondb.py`, `ui/protondb_dialog.py`). Opt-in; 7-day disk cache. |
| 2.2 | Winetricks verb picker UI | **Shipped** (`backend/winetricks_catalog.py`, `ui/winetricks_picker.py`). |
| 2.3 | Redist auto-scan post-install | **Shipped** (`backend/redist_scanner.py`, `ui/redist_dialog.py`). |
| 2.4 | Heuristic verb suggestions from PE imports | Scan the main exe for `d3d9.dll`, `msvcr120.dll`, `mfplat.dll`, `xaudio2_7.dll` → suggest `d3dx9`, `vcrun2013`, `mf-install`, `xact`. |
| 2.5 | Media Foundation install | `mf-install`; huge class of modern titles need it for cutscene playback. |
| 2.6 | Core fonts / CJK fonts | `corefonts`, `cjkfonts`; crash-fix class for font-less prefixes. |
| 2.7 | FAudio | XAudio2 compatibility. |
| 2.8 | DXVK / VKD3D version management | Pin a version per app, upgrade independently, not just a bool. |

## 3. Per-app launch knobs (missing from `AppConfig`)

Today: `arch`, `winetricks_verbs`, `env`, `launch_args`, `gamemode`, `mangohud`, `dll_overrides`, `dxvk`, `vkd3d`, `gpu_index`.

| # | Feature | Env var / mechanism |
|---|---|---|
| 3.1 | ESYNC / FSYNC toggle | `WINEESYNC`, `WINEFSYNC` |
| 3.2 | Windows version override | Per-prefix `winecfg` setting; several games need win7/winxp. |
| 3.3 | Virtual desktop mode | `explorer /desktop=Game,WxH` for misbehaving fullscreen games. |
| 3.4 | Forced resolution / display | Pick monitor, resolution, refresh rate. |
| 3.5 | NVAPI / DLSS | `PROTON_ENABLE_NVAPI=1`, `DXVK_ENABLE_NVAPI=1` |
| 3.6 | Gamescope wrapper | **Shipped** (`AppConfig.gamescope`, `launcher._build_gamescope_prefix`, settings group in `app_settings_dialog.py`). |
| 3.7 | Wayland driver toggle | Proton-GE `WINE_WAYLAND_DRIVER` |
| 3.8 | CPU affinity / thread cap | `taskset`; ancient titles break with many cores. |
| 3.9 | Locale override | `LANG=ja_JP.UTF-8` for region-locked titles. |
| 3.10 | DXVK state cache path | `DXVK_STATE_CACHE_PATH` per-app — avoid one giant shared cache. |
| 3.11 | Pre-launch / post-launch hooks | Shell snippets: mount ISO, kill Discord, restore xrandr. |

## 4. Prefix management

Today: one prefix per app, `winecfg` / `regedit` / `wineserver -k` via `prefix_tools.py`.

| # | Feature | Notes |
|---|---|---|
| 4.1 | Prefix templates | Reusable preset bundles ("DX9 retro", "modern DX11", "UE4 prereqs") applied on prefix create. |
| 4.2 | Prefix clone | Duplicate a known-good prefix as the starting point for a new install. |
| 4.3 | Prefix upgrade (`wineboot -u`) | Run when the user switches runtime. |
| 4.4 | Per-app ProtonFixes overlay file | Author small shims without patching Proton. |

## 5. Detection & diagnostics

| # | Feature | Notes |
|---|---|---|
| 5.1 | Umu-launcher integration | Canonical way to run Proton outside Steam; replaces the hand-rolled `STEAM_COMPAT_*` env and gets game-id-based ProtonFixes for free. |
| 5.2 | Crash / short-run detection | If the game exits in <5s with non-zero rc, surface log tail in a dialog; offer "run in Wine debug" retry. |
| 5.3 | `wine --version` / prefix arch probe | Surface mismatches between prefix arch and runtime. |
| 5.4 | First-run checklist | Compositor off, CPU governor, sleep inhibit, controller detected. |

## 6. Runtime (during play)

| # | Feature | Notes |
|---|---|---|
| 6.1 | Sleep / screensaver inhibit during play | `systemd-inhibit` or GNOME Inhibit portal. |
| 6.2 | Resolution restore on exit | Save xrandr state pre-launch, restore if the game crashes and leaves it mangled. |
| 6.3 | Ad-hoc "Just Run This EXE" | Transient prefix, no library entry, for testing. |

---

## Highest-leverage six (picked for `feature_implementation.md`) — ✅ all shipped

All six landed in commit `3ba6e89` (2026-04-18). See `feature_implementation.md` for per-feature implementation notes.

1. **ZIP / archive installers** (§1.1) — `backend/archive_installer.py`
2. **MSI support** (§1.2) — `generic_installer.run_installer`
3. **ProtonDB lookup + auto-apply** (§2.1) — `backend/protondb.py`, `ui/protondb_dialog.py`
4. **Winetricks verb picker UI** (§2.2) — `backend/winetricks_catalog.py`, `ui/winetricks_picker.py`
5. **Redist auto-scan post-install** (§2.3) — `backend/redist_scanner.py`, `ui/redist_dialog.py`
6. **Gamescope wrapper** (§3.6) — `AppConfig.gamescope`, `launcher._build_gamescope_prefix`

Rationale: the first five each unlock or fix a large class of games that currently fail at install or first launch. Gamescope is the single biggest quality-of-play lever not yet exposed.
