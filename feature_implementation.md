# Feature Implementation Plan — Six High-Leverage Features

This plan covers:

1. ZIP / archive installers
2. MSI installer support
3. ProtonDB lookup + auto-apply
4. Winetricks verb picker UI
5. Redist auto-scan post-install
6. Gamescope wrapper

Each section lists: goal, data model impact, new modules, modified files, UX flow, dependencies, test plan, and open questions.

---

## 1. ZIP / archive installers

### Goal
Accept `.zip`, `.7z`, `.rar` as first-class installer sources for games that ship as plain archives (itch.io, abandonware, many indies). No Wine-install phase; extract to `installs_dir/<app_id>/`, auto-detect the main exe, create a fresh prefix, register.

### Data model
No schema change. `AppSource.MANUAL` suffices; optionally add `AppSource.ARCHIVE` for analytics. Skip unless useful.

### New module: `exwin/backend/archive_installer.py`

```
detect_archive_type(path: Path) -> str | None
    # return "zip" | "7z" | "rar" | None (by magic bytes, not extension)

extract_archive(src: Path, dest: Path, on_progress: Callable[[int,int],None]|None) -> None
    # zip   -> stdlib zipfile
    # 7z    -> `7z x -o<dest> <src>` (p7zip)
    # rar   -> `unar -o <dest> <src>` (already a dep)
    # progress: count members via `7z l` / zipfile.namelist, tick per extracted file

scan_install_dir_for_exes(root: Path) -> list[Path]
    # Like scan_candidate_exes but on a regular folder tree (no drive_c).
    # Reuse _SKIP_DIRS / _SKIP_EXES / _UNLIKELY_STEMS from generic_installer.
```

Refactor: lift filtering constants out of `generic_installer.py` into a small shared module (e.g. `backend/exe_filter.py`) so both archive and Wine paths use the same heuristics.

### Modified files
- `exwin/backend/generic_installer.py` — `detect_installer_type()` grows to return `"archive"` when `detect_archive_type()` matches. Return-type docstring updated.
- `exwin/ui/install_dialog.py`
  - File filter gains `*.zip *.7z *.rar` patterns.
  - `_probe_thread` branches on `installer_type == "archive"` → new `_on_archive_detected`.
  - New confirm page (or reuse generic confirm, hiding Wine-specific rows): name field, runtime, arch, verbs, DXVK/VKD3D.
  - New install path: extract → `scan_install_dir_for_exes` → exe-select page (reuse existing `exe_select` page — it already lets the user pick) → `finalize_generic_install` with `install_dir` set to the extracted folder (not prefix root) and a fresh prefix created via `create_prefix()`.
- `exwin/ui/install_pages.py` — new `build_confirm_archive_page` or extend generic.
- `exwin/backend/install_worker.py` — add `install_archive()` that orchestrates extract → prefix-create → winetricks/DXVK/VKD3D → insert_app.

### Subtlety: install_path vs prefix_path
For archive installs these diverge (unlike generic Wine installs where the prefix IS the install root). `finalize_generic_install` currently assumes `install_path == prefix_path`. Either (a) generalise it to accept separate paths, or (b) bypass it and inline the final insert in `install_archive()`. (b) is cleaner — there's enough divergence to justify a second finaliser.

### Dependencies
- `p7zip-full` (for 7z) — add to Flatpak manifest.
- `unar` (already present).
- stdlib `zipfile` for zip.

### UX flow
1. User picks `game.zip` from file dialog (or drags it onto library).
2. Welcome → probing → confirm-archive (shows member count + total size, runtime/arch/DXVK).
3. Extracting page with progress bar (files extracted / total).
4. Prefix create + optional winetricks / DXVK / VKD3D.
5. Exe-select page if >1 candidate; auto-pick if 1.
6. Done.

### Test plan
- `tests/test_archive_installer.py`:
  - `detect_archive_type` against tiny fixtures (a 10-byte zip, 7z, rar, and a non-archive).
  - `extract_archive` creates expected files, respects destination.
  - Progress callback fires (mock).
- Manual: install an itch.io zip end-to-end.

### Open questions
- Archives with a single top-level folder vs flat — flatten one level when only one top-level directory exists? Most installers do this; worth implementing.
- Password-protected archives — punt (surface error message only).

---

## 2. MSI installer support

### Goal
Accept `.msi` files and run them via `wine msiexec /i`.

### Data model
No change.

### Modified files
- `exwin/backend/generic_installer.py`
  - `detect_installer_type()`: if suffix is `.msi`, return `"msi"`.
  - New `run_msi_installer(installer_path, p_root, runtime, arch)` — identical to `run_wine_installer` but `cmd = [wine, "msiexec", "/i", str(installer_path)]` (for Proton: `proton run msiexec /i …`).
- `exwin/ui/install_dialog.py`
  - File filter adds `*.msi`.
  - `_probe_thread` treats `"msi"` the same as `"generic"` for UI purposes but flips an internal flag so `_wine_installer_thread` calls `run_msi_installer` instead of `run_wine_installer`. Simplest implementation: unify via a single `run_installer(installer_path, kind, …)` that chooses cmd by kind.

### UX flow
Same as generic Wine install — confirm page, run installer interactively, exe-select. User-visible change is just: the file picker now accepts `.msi`.

### Test plan
- `tests/test_generic_installer.py::test_detect_msi` — fixture `.msi` file (empty, valid MSI header) returns `"msi"`.
- Manual: install a small MSI (e.g. notepad++ MSI).

### Open questions
- Should we expose `/qn` (silent MSI install) as a toggle? Probably not — most users want the wizard to choose the install path.

---

## 3. ProtonDB lookup + auto-apply

### Goal
For any library entry, look up ProtonDB rating + top report text, show it in the UI, and offer one-click application of common tweaks (launch args, env vars, verbs) found in the reports.

### Data model
Add to DB (new column via `ALTER TABLE` migration pattern already used in `schema.py`):
- `apps.steam_appid INTEGER` — cached Steam app id used for ProtonDB lookups (may be null for GOG titles until resolved).
- `apps.protondb_tier TEXT` — "platinum" | "gold" | "silver" | "bronze" | "borked" | null.
- `apps.protondb_fetched_at TEXT` — ISO timestamp; refresh older than 7 days.

### New module: `exwin/backend/protondb.py`

```
resolve_steam_appid(name: str) -> int | None
    # GET https://store.steampowered.com/api/storesearch/?term=<name>&cc=us&l=en
    # return first hit's appid

fetch_summary(appid: int) -> dict
    # GET https://www.protondb.com/api/v1/reports/summaries/<appid>.json
    # returns {"tier": "gold", "confidence": "good", "score": 0.78, "total": 134, ...}

fetch_top_reports(appid: int, limit: int = 5) -> list[dict]
    # GET https://www.protondb.com/api/v1/reports/app/<appid>.json (or similar)
    # returns reports w/ text body, timestamp, tier, proton version

extract_tweaks(reports: list[dict]) -> ProtonTweaks
    # regex-mine report bodies for:
    #   - launch args like "PROTON_NO_ESYNC=1 %command%" / "-dx11 -windowed"
    #   - winetricks verbs "winetricks vcrun2019"
    #   - env like "WINEDLLOVERRIDES=dinput8=n"
    # return a ProtonTweaks dataclass with launch_args, env, verbs, dll_overrides
```

Cache responses in `~/.exwin/cache/protondb/<appid>.json` (honour `protondb_fetched_at`). Use `urllib` (no new deps).

### New module: `exwin/backend/steam_appid.py`

Name → Steam appid resolution; isolated so `protondb.py` stays focused on reports. Small alias table for stubborn cases (e.g. GOG "The Witcher 3: Wild Hunt" vs Steam "The Witcher 3: Wild Hunt – Complete Edition") could live here — punt until a real mismatch is hit.

### Modified files
- `exwin/db/schema.py` — ALTER TABLE for the three new columns.
- `exwin/db/apps.py` — `update_protondb_cache(app_id, appid, tier, fetched_at)`.
- `exwin/ui/app_detail_dialog.py` — add "ProtonDB" row showing tier icon + fetched-at; "Check ProtonDB" button → spawn thread → populate.
- `exwin/ui/protondb_dialog.py` (new) — modal showing summary, top 5 reports, and an "Apply Tweaks" button that diffs the parsed tweaks against current `AppConfig` and shows checkboxes for what to apply. On confirm, writes via `save_app_config`.

### UX flow
1. User opens a game's detail dialog.
2. Clicks "Check ProtonDB".
3. Background fetch: resolve appid (if cached, skip) → fetch summary → fetch reports. Spinner.
4. Dialog shows tier + report list + parsed tweaks (checkboxes, pre-checked for the most-upvoted ones).
5. Apply → `AppConfig` updated → toast.

### Dependencies
None (urllib); optionally `beautifulsoup4` if HTML scraping becomes necessary, but the JSON API path should cover it.

### Test plan
- `tests/test_protondb.py`:
  - `extract_tweaks` against fixture report bodies — ensure common patterns parse correctly.
  - `fetch_summary` with monkeypatched urlopen (fixture JSON).
  - Cache: second call within TTL does not hit network; call after TTL does.
- Manual: check a known platinum (Portal 2, appid 620) and a known borked title.

### Open questions
- Rate limiting — ProtonDB doesn't advertise a limit; cache aggressively and throttle to 1 req/sec.
- Offline-first principle — this is an opt-in online feature. Gate behind a "Allow online lookups" setting in `Config`? At minimum, never auto-fetch: require an explicit button click.
- Terms of service — confirm ProtonDB's API is safe to consume from a client this way (their web app does it).

---

## 4. Winetricks verb picker UI

### Goal
Replace the freeform "Winetricks Verbs" text entry (in `install_dialog.py`, `add_existing_dialog.py`, `app_settings_dialog.py`) with a searchable picker showing verb names, categories, and descriptions. Users stop guessing verb names.

### Data model
No change — `AppConfig.winetricks_verbs: list[str]` remains the storage format.

### New module: `exwin/backend/winetricks_catalog.py`

```
@dataclass
class Verb:
    name: str          # "vcrun2019"
    category: str      # "dlls" | "fonts" | "settings" | "apps" | ...
    description: str   # "MS Visual C++ 2015-2019 Redistributable"

def load_catalog(force_refresh: bool = False) -> list[Verb]:
    # Cached at ~/.exwin/cache/winetricks_verbs.json
    # Regenerate by parsing `winetricks --list-all` (or per-category lists)
    # Catalog ships with a bundled fallback JSON in exwin/data/winetricks_verbs.json
    #   so the picker works even before first `winetricks --list-all` run.
```

Parsing `winetricks --list-all` output: lines are `verbname         One-line description` with variable whitespace. Split on first run of ≥2 spaces.

### New module: `exwin/ui/winetricks_picker.py`

```
class WinetricksPicker(Adw.Dialog):
    def __init__(self, selected: list[str], on_confirm: Callable[[list[str]], None]):
        # - Search entry (filters by name OR description substring, case-insensitive)
        # - AdwPreferencesGroup per category (collapsible)
        # - Each row: AdwActionRow with checkbox suffix, title=verb, subtitle=description
        # - Bottom bar: selected-count label + Apply + Cancel
```

### Modified files
- `exwin/ui/install_dialog.py` (confirm_gog + confirm_generic pages), `exwin/ui/add_existing_dialog.py`, `exwin/ui/app_settings_dialog.py`:
  - Replace the `Adw.EntryRow(title="Winetricks Verbs")` with an `Adw.ActionRow` showing the current selection count + "Edit…" button.
  - Button opens `WinetricksPicker(selected=current_verbs, on_confirm=lambda v: self._current_verbs=v)`.
  - Also expose presets ("DirectX 9 base", "Modern .NET", "FAudio + MF") as quick-apply buttons inside the picker — presets are a small hand-curated list in `winetricks_catalog.py`.
- `exwin/ui/install_pages.py` — update the builder functions that currently yield a text row.

### Dependencies
None; parses existing `winetricks` output.

### Test plan
- `tests/test_winetricks_catalog.py`:
  - Parse a fixture `--list-all` output → expected `Verb` list.
  - Cache: second call uses cached JSON.
  - Fallback: catalog loads even when `winetricks` binary is absent (uses bundled JSON).
- UI smoke test: open picker, toggle a verb, confirm selection round-trips.

### Open questions
- Ship a curated "popular 30" list on top? Most users want vcrun2019, corefonts, d3dx9, mf-install, dotnet48 — putting them in a "Popular" group at the top beats dropdown diving.

---

## 5. Redist auto-scan post-install

### Goal
After a game installs, walk its install dir for known redistributable installers/DLLs. For each found, either (a) run the installer under Wine in the game's prefix, or (b) map to the equivalent `winetricks` verb and offer to apply. Drastically reduces "installed but crashes on launch" cases.

### Data model
No change.

### New module: `exwin/backend/redist_scanner.py`

```
@dataclass
class RedistFinding:
    path: Path              # absolute path to installer or indicator file
    kind: str               # stable id: "vcredist-2019-x64", "dxsetup", "oalinst", ...
    description: str        # "Visual C++ 2015-2019 Redistributable (x64)"
    action: str             # "run" | "verb"
    payload: str            # exe args for "run", winetricks verb for "verb"

_PATTERNS = [
    # (regex/glob on filename, kind, description, action, payload)
    (r"vc_?redist.*x64\.exe$",   "vcredist-x64",  "...", "verb", "vcrun2019"),
    (r"vc_?redist.*x86\.exe$",   "vcredist-x86",  "...", "verb", "vcrun2019"),
    (r"dxsetup\.exe$",           "dxsetup",       "...", "run",  "/silent"),
    (r"oalinst\.exe$",           "openal",        "...", "run",  "/s"),
    (r"physx.*_systemsoftware\.exe$", "physx",    "...", "run",  "/passive"),
    (r"UE[34]PrereqSetup_x64\.exe$",  "ue-prereq","...", "run",  "/quiet"),
    (r"dotnetfx\.exe$",          "dotnetfx",      "...", "verb", "dotnet48"),
    # ... ~20 entries total
]

def scan(install_dir: Path) -> list[RedistFinding]:
    # recursively match filenames against _PATTERNS; skip anything under 'uninst*' dirs

def apply_finding(finding: RedistFinding, prefix_root: Path, runtime: Runtime,
                  on_log: Callable[[str],None]|None = None) -> int:
    # "run" → Popen(wine, finding.path, finding.payload.split()).wait()
    # "verb" → run_verbs(prefix_root, [finding.payload], runtime).wait()
    # returns exit code
```

### Modified files
- `exwin/backend/install_worker.py` — at end of `install_gog()` / `install_archive()` / after `run_wine_installer()` finalisation, call `scan()`; stash findings on the installed app for the UI to present. (Or return them from the install worker and let the UI drive.)
- `exwin/ui/install_dialog.py` — after `_on_install_done`, if findings exist, transition to a new "redist" page: list of findings with per-row checkboxes (pre-checked), "Run selected" / "Skip" buttons. "Run" iterates, streaming log to the existing log view, tracks success/fail per item.
- `exwin/ui/install_pages.py` — new `build_redist_page(on_run, on_skip)`.

### Dependencies
None.

### Test plan
- `tests/test_redist_scanner.py`:
  - Fixture directory with synthetic filenames → `scan()` returns expected findings with correct kinds.
  - `apply_finding` for a "verb" finding calls `run_verbs` with the right args (mock).
  - `apply_finding` for a "run" finding builds the right wine cmd (mock Popen).
- Manual: install a UE4 game; confirm `UE4PrereqSetup_x64.exe` is detected and applied.

### Open questions
- Some redists must run **before** first launch (vcrun2019), others are effectively optional (OpenAL). Mark each pattern with `recommended: bool` to drive default checkbox state.
- Should this also run opportunistically on a "Check prerequisites" button in AppDetailDialog, not just post-install?  Yes — cheap to expose; games added via Add-Existing would benefit.

---

## 6. Gamescope wrapper

### Goal
Optional per-app `gamescope` compositor — HDR, FSR/NIS upscaling, frame cap, aspect correction, steam-deck-style fullscreen. Biggest play-quality lever not currently exposed.

### Data model
Extend `AppConfig`:

```
@dataclass
class GamescopeConfig:
    enabled: bool = False
    output_width: int = 0       # -W; 0 = omit (gamescope chooses)
    output_height: int = 0      # -H
    game_width: int = 0         # -w; internal res
    game_height: int = 0        # -h
    fullscreen: bool = True     # -f
    upscale_filter: str = ""    # "" | "fsr" | "nis" | "linear" | "integer"; -F
    upscale_sharpness: int = 0  # --sharpness / --fsr-sharpness
    hdr: bool = False           # --hdr-enabled (needs compat gamescope build)
    frame_limit: int = 0        # -r (or --fps-limit on newer builds)
    mangoapp: bool = False      # --mangoapp for overlay inside nested compositor
    extra_args: str = ""        # raw escape hatch

@dataclass
class AppConfig:
    # ... existing fields
    gamescope: GamescopeConfig = field(default_factory=GamescopeConfig)
```

TOML round-trip: new `[gamescope]` table; absent table → defaults.

### Modified files
- `exwin/backend/app_config.py` — add field + TOML read/write.
- `exwin/backend/launcher.py::_build_command`:
  - After building the Wine/Proton command, if `app_config.gamescope.enabled` and `shutil.which("gamescope")`, build the gamescope prefix and prepend:
    ```
    gs = ["gamescope"]
    gs += ["-W", str(w)] if w else []
    gs += ["-H", str(h)] if h else []
    gs += ["-w", str(gw)] if gw else []
    gs += ["-h", str(gh)] if gh else []
    gs += ["-f"] if fullscreen else []
    gs += ["-F", upscale_filter] if upscale_filter else []
    gs += ["--hdr-enabled"] if hdr else []
    gs += ["-r", str(frame_limit)] if frame_limit else []
    gs += ["--mangoapp"] if mangoapp else []
    gs += shlex.split(extra_args)
    gs += ["--"]
    cmd = gs + cmd
    ```
  - Order: `gamescope -- gamemoderun mangohud proton run <exe>`. `gamescope` wraps everything because it provides the display surface. If `mangoapp` is set, swap in the mangohud behaviour it replaces.
  - If `gamescope` binary is missing, silently skip (matching how gamemoderun/mangohud are handled) and log a warning to the app log.

- `exwin/ui/app_settings_dialog.py` — new "Gamescope" group under Launch, built conditionally on `shutil.which("gamescope")` (show a disabled-with-note row when absent):
  - SwitchRow: Enable
  - EntryRows: Output WxH, Game WxH (blank = auto)
  - SwitchRow: Fullscreen
  - ComboRow: Upscale filter (none/fsr/nis/linear/integer)
  - SpinRow: Sharpness (0–20)
  - SwitchRow: HDR (disabled + tooltip if non-HDR build)
  - SpinRow: FPS cap (0 = no cap)
  - SwitchRow: MangoApp overlay
  - EntryRow: Extra args

### Dependencies
- `gamescope` binary. Add to Flatpak manifest (`org.freedesktop.Platform.Gamescope` extension where available) or flag it as a user-installed host dep.

### Test plan
- `tests/test_launcher.py`:
  - `test_gamescope_wraps_cmd`: `AppConfig(gamescope=GamescopeConfig(enabled=True, output_width=1920, upscale_filter="fsr"))` + `shutil.which` patched → first element of cmd is `"gamescope"`, contains `-W 1920 -F fsr --`, real cmd follows the `--`.
  - `test_gamescope_missing_binary`: `shutil.which("gamescope")` returns None → cmd unchanged, warning logged.
- `tests/test_app_config.py`: round-trip a `GamescopeConfig` through TOML.
- Manual: enable gamescope FSR on a windowed game; verify scaling.

### Open questions
- HDR needs a gamescope build that supports it — detect by running `gamescope --help | grep hdr` at scan time; cache result; disable the HDR switch if unsupported.
- Interaction with MangoHud env-var config: when `mangoapp` is active, the existing `mangohud` cmd wrapper should be suppressed automatically.

---

## Suggested delivery order

1. **MSI** (§2) — trivial, clears a class of "please pick a `.exe`" friction instantly.
2. **ZIP/archive installers** (§1) — medium effort, unlocks itch.io library.
3. **Winetricks picker** (§4) — self-contained UI win; prerequisite UX for §5 ("here's what we suggest" lands better when the picker can preview the verbs).
4. **Redist auto-scan** (§5) — builds on §4 for the "offer verb" path.
5. **Gamescope** (§6) — self-contained launch-side feature; no ordering constraint but best done once installs are reliable.
6. **ProtonDB** (§3) — most moving parts (network, caching, report parsing, DB schema) and requires an online-lookups opt-in; do last.

## Cross-cutting notes

- **Flatpak manifest**: §1 (`p7zip`), §6 (`gamescope` extension). Bundle where possible; document host deps otherwise.
- **DB migrations**: only §3 adds columns. Use the existing `ALTER TABLE … try/except OperationalError` pattern in `schema.py`.
- **CLI parity** (`exwin/__main__.py`): once §6 lands, `--launch` must respect the gamescope block. §3-§5 are install/config features — no CLI surface needed.
- **Offline-first principle**: only §3 is network-dependent. Gate it behind an explicit user action; never fetch automatically.
