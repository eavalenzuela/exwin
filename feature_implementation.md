# Feature Implementation Plan — Next Five

Previous batch of six install/launch features (archives, MSI, winetricks picker, redist scan, gamescope, ProtonDB) shipped in commit `3ba6e89` (2026-04-18).

This plan covers the next five items from `functionality_exploration.md`:

1. Crash / short-run detection (§5.2)
2. Folder / portable-game import (§1.8, covers §1.10 single-file exe as a degenerate case)
3. Prefix upgrade via `wineboot -u` (§4.3)
4. Pre-launch / post-launch shell hooks (§3.11)
5. Umu-launcher integration (§5.1)

Each section lists: goal, data model impact, new modules, modified files, UX flow, dependencies, test plan, and open questions.

---

## 1. Crash / short-run detection

### Goal
When a launched game exits quickly with a non-zero rc, pop a dialog showing the tail of the app log and offering: "Open ProtonDB", "Re-run with Wine debug", "View full log", "Copy log". Every crash becomes an actionable event instead of a silent failure.

### Data model
Config-level knobs only:
- `Config.crash_threshold_seconds: int = 5` — runs shorter than this with non-zero rc trigger the dialog.
- No DB/schema change.

### New module: `exwin/ui/crash_dialog.py`

```
class CrashDialog(Adw.Dialog):
    def __init__(self, info: CrashInfo, on_protondb, on_debug_rerun, on_open_log):
        # AdwStatusPage header: "<app name> exited after 2.1s (code 1)"
        # Scrollable text view: last ~40 lines of log
        # Buttons: ProtonDB ↗ (disabled if no steam_appid), Rerun in Debug, Open Log, Copy Log, Close
```

### New module: `exwin/backend/crash_detect.py`

```
@dataclass
class CrashInfo:
    app: AppEntry
    rc: int
    duration_seconds: float
    log_tail: str          # last ~40 lines
    log_path: Path
    runtime: Runtime | None
```

`build_crash_info(app, rc, duration, log_path)` reads the tail and assembles the struct.

### Modified files
- `exwin/backend/launcher.py::Launcher`:
  - Record `_launch_started_at: float` on launch (monotonic).
  - In `_watch`, after Popen exits, compute duration.
  - Track `_user_stopped: bool` — set True from the existing `stop()` method, skip crash detection when set (user initiated).
  - If `rc != 0 and duration < config.crash_threshold_seconds and not _user_stopped`, call new `on_crash: Callable[[CrashInfo], None] | None` via `GLib.idle_add`.
- `exwin/window.py` — register `on_crash = _show_crash_dialog`; dialog opens with ProtonDB + debug-rerun wired to existing launcher.
- Debug rerun: call `launcher.launch(app, runtime, app_config)` with `WINEDEBUG=+all,+relay,+seh` merged into env (transient — not persisted to `AppConfig`). Log to `crash-debug-<timestamp>.log` alongside the normal log.
- `exwin/__main__.py::_cmd_launch` — headless launch prints the crash-info summary to stderr instead of opening a dialog.

### UX flow
1. User launches game.
2. Game exits rc=1 in 2.1s.
3. `_watch` detects short run, fires `on_crash`.
4. Dialog pops: header "Baldur's Gate 3 exited after 2.1s (code 1)", log tail, action buttons.
5. User clicks "Rerun in Debug" → second launch with WINEDEBUG env; same dialog re-opens on failure with fatter log.

### Dependencies
None.

### Test plan
- `tests/test_launcher.py`:
  - `test_short_nonzero_run_triggers_on_crash` — fake Popen exits in 1s w/ rc=1; `on_crash` called w/ correct duration.
  - `test_long_run_does_not_trigger` — slow Popen exit, no callback.
  - `test_zero_rc_does_not_trigger` — even when fast.
  - `test_user_stop_suppresses_crash` — call `launcher.stop()` mid-run; no callback.
- `tests/test_crash_detect.py` — `build_crash_info` reads tail correctly; handles missing log file.
- Manual: launch a deliberately broken config, verify dialog + debug-rerun path.

### Open questions
- Threshold: hard-code 5s or adaptive? Hard-code + config-tunable; adaptive ("compare to this app's median successful run") is over-engineering for v1.
- Do we crash-detect Add-Existing dry-runs? Yes — same launcher code path.
- How big should the log tail be? 40 lines covers most Wine stderr patterns; add "Open Full Log" for the rest.

---

## 2. Folder / portable-game import

### Goal
Replace the awkward "Add Existing Game" flow (user hand-picks an exe) with: pick a folder, background-scan, pre-select the best candidate, wrap in a fresh prefix. Handles single-file `.exe` portable freeware (§1.10) as a degenerate case.

### Data model
No change. `AppSource.MANUAL` suffices.

### New module: `exwin/backend/folder_import.py`

```
def scan_folder_for_exes(root: Path) -> list[Path]:
    # Walk root; apply exe_filter.SKIP_DIRS / SKIP_EXE_NAMES.
    # Sort: pick_best_exe's preferred result first, then by size desc.

def import_folder(
    folder: Path,
    app_name: str,
    runtime: Runtime,
    app_config: AppConfig,
    config: Config,
    copy: bool = True,
    on_progress: Callable[[int,int],None] | None = None,
) -> AppEntry:
    # If copy=True: shutil.copytree(folder, installs_dir/app_id)
    # If copy=False: link — install_path points at the original folder
    # Create fresh prefix, apply winetricks verbs / DXVK / VKD3D
    # Insert app with exe_path relative to install_path
```

### Modified files
- `exwin/backend/exe_filter.py` — add `scan_folder_for_exes` (or expose it as a re-export; the existing `pick_best_exe` stays).
- `exwin/ui/add_existing_dialog.py`:
  - Add top-of-dialog mode picker: "Folder (recommended)" / "Single executable" radio group.
  - Folder mode: folder-picker row → background scan → confirm page w/ detected exes as radio list (pre-select `pick_best_exe` result), name auto-filled from folder basename, existing runtime/arch/verbs/DXVK/VKD3D/Gamescope rows.
  - Single-exe mode: preserved for backward compat.
  - "Leave files in place (don't copy)" checkbox in Folder mode, with a warning toast: "moving the folder will break this entry."
- `exwin/__main__.py` — optional CLI subcommand `add-folder <path> [--name …] [--runtime …] [--link]`. Nice-to-have; defer if out of scope.

### Subtleties
- Registry-based Windows installs: if scan finds `uninst*.exe` / `setup.exe` but no normal binary, show a hint banner: "This looks like a registered install; use Single-executable mode and point at the real binary."
- Case-insensitive filesystem quirks (NTFS-mounted drives, SMB): `scan_folder_for_exes` uses `Path.glob` with case-insensitive patterns where needed.
- Symlink loops: use `os.walk(followlinks=False)`.

### UX flow
1. User opens Add Existing → picks "Folder".
2. Picks `/media/games/DiabloII/`.
3. Background scan → `Game.exe`, `Editor.exe`, `Uninstall.exe`.
4. Confirm page: radio list, `Game.exe` pre-checked, name prefilled "DiabloII".
5. Runtime/arch/verbs/DXVK/VKD3D/Gamescope rows (reuse existing install-dialog page builder).
6. Confirm → copy or link → fresh prefix → register → library refresh.

### Dependencies
None.

### Test plan
- `tests/test_folder_import.py`:
  - Fixture folder with multiple exes → `scan_folder_for_exes` returns filtered list, skips uninstall/setup/redist.
  - `import_folder(copy=True)` end-to-end with fake runtime: prefix created, app inserted, paths correct.
  - `import_folder(copy=False)` — install_path points at source folder; no copy.
  - Single-exe (degenerate) case: folder w/ one exe → app registered.
- UI smoke: open Add Existing, run folder flow in copy mode.

### Open questions
- Batch "scan every subfolder of X and offer each as a candidate": skip for v1; §1.9 queued-install territory.
- `.lnk` resolution (§1.6): out of scope; can fold in later.

---

## 3. Prefix upgrade (`wineboot -u`)

### Goal
Expose "Upgrade Prefix" next to the existing "Rebuild Prefix" button. Runs `wineboot -u` inside the prefix to refresh system DLLs after a runtime switch without blowing away user data.

### Data model
No change.

### Modified files
- `exwin/backend/prefix_tools.py`:
  - Add `upgrade_prefix(app: AppEntry, runtime: Runtime) -> subprocess.Popen`.
  - Proton runtime: `[proton, "run", "wineboot", "-u"]` with `STEAM_COMPAT_DATA_PATH` + `STEAM_COMPAT_CLIENT_INSTALL_PATH` + `SteamAppId=0` (same env as launcher).
  - Wine runtime: `[<prefix>/bin/wine, "wineboot", "-u"]` with `WINEPREFIX`.
  - Returns Popen; caller watches.
- `exwin/ui/app_detail_dialog.py`:
  - New flat button "Upgrade Prefix" next to Rebuild Prefix.
  - Tooltip distinguishing the two: "Rebuild: wipe + recreate (reinstalls DXVK / VKD3D / verbs). Upgrade: run `wineboot -u` on the existing prefix to refresh system DLLs — keeps user data."
  - Runs in a worker thread, spinner while live, log streamed to the existing log viewer.

### Dependencies
None.

### Test plan
- `tests/test_prefix_tools.py`:
  - `test_upgrade_prefix_proton` — mocked Popen; cmd == `[proton, "run", "wineboot", "-u"]`, env has `STEAM_COMPAT_DATA_PATH`.
  - `test_upgrade_prefix_wine` — cmd starts with `<prefix>/bin/wine`, env has `WINEPREFIX`.
  - Exit-code surfacing: non-zero propagated.
- Manual: switch game from GE-Proton9-1 → GE-Proton9-27, invoke Upgrade, no error.

### Open questions
- Auto-prompt on runtime switch? Offer a toast "Runtime changed — upgrade prefix?" after the AppDetailDialog runtime-combo edit. Cheap and discoverable; add in same PR. ANSWER: Yes.
- For Wine prefixes where `wine64` is preferred (see fix commit `5fa0ff3`): use the same wine64/wine resolution logic as the launcher. Factor out into a shared helper if not already one. 

---

## 4. Pre-launch / post-launch hooks (curated toggles + shell escape hatch)

### Goal
Per-app actions that run before/after the game, exposed as a hybrid:
- **Curated toggles** — a small, portable checklist covering the 80% case (mount a disc image, kill conflicting apps, suspend the compositor, boost the CPU governor). Zero shell knowledge required. Reversible on exit where applicable.
- **Shell escape hatch** — freeform pre/post shell snippets for anything not covered by a toggle.

Modelled after the same two-layer pattern as the winetricks picker (curated presets on top, full catalog underneath).

### Data model
New nested `HookConfig` on `AppConfig`. `[hooks]` TOML table omitted when all defaults.

```
@dataclass
class HookConfig:
    # Curated toggles (reversed on exit where applicable)
    mount_iso: str = ""                       # path; empty = disabled
    kill_processes: list[str] = field(default_factory=list)  # pkill -x names, pre-launch
    suspend_kde_compositor: bool = False      # KDE only; no-op elsewhere
    cpu_performance_governor: bool = False    # gracefully disabled if no user-level path

    # Escape hatch
    pre_launch_cmd: str = ""                  # non-zero aborts launch
    post_launch_cmd: str = ""                 # best-effort; errors logged
    post_launch_on_crash_only: bool = False

@dataclass
class AppConfig:
    # ... existing fields
    hooks: HookConfig = field(default_factory=HookConfig)
```

### New module: `exwin/backend/hooks.py`

```
@dataclass
class HookState:
    # What was actually applied — used to reverse on exit.
    iso_loop_device: str | None = None
    iso_mount_point: Path | None = None
    compositor_was_active: bool = False
    prior_power_profile: str | None = None
    killed_processes: list[str] = field(default_factory=list)  # informational

def apply_pre_hooks(hooks: HookConfig, env: dict, log: Callable[[str],None]) -> HookState
    # Toggle order: mount ISO → kill processes → suspend compositor → perf governor → pre_launch_cmd.
    # Each toggle is best-effort (log + continue on failure).
    # pre_launch_cmd failure aborts launch (raises HookAbort; caller fires on_crash).

def apply_post_hooks(hooks: HookConfig, state: HookState, rc: int,
                     env: dict, log: Callable[[str],None]) -> None
    # Order: post_launch_cmd (gated) → restore governor → resume compositor → unmount ISO.
    # Killed processes are NOT restarted (autostart apps self-recover; the rest was intentional).

# Helpers (private):
def _mount_iso(path: Path, log) -> tuple[str, Path]      # udisksctl loop-setup + mount; fuseiso fallback
def _unmount_iso(state, log)
def _kill_processes(names: list[str], log) -> list[str]  # pkill -x each; name validated against [A-Za-z0-9._-]+
def _suspend_kde_compositor(log) -> bool                 # qdbus org.kde.KWin /Compositor suspend; detects KDE via $XDG_CURRENT_DESKTOP
def _resume_kde_compositor(was_active: bool, log)
def _set_performance_governor(log) -> str | None         # powerprofilesctl set performance; returns prior profile
def _restore_governor(prior: str | None, log)
def _running_in_kde() -> bool
def _governor_tool_available() -> str | None             # "powerprofilesctl" | "cpupower" | None
```

Implementation notes:
- **ISO mount**: prefer `udisksctl loop-setup --file <iso>` → DBus returns the loop device path; `udisksctl mount -b <loop>` → returns mount point. Fully user-level, no root. Fallback: `fuseiso` when udisks2 unavailable. Surface the mount point via env var `EXWIN_ISO_MOUNT` so the escape-hatch shell and launch_args can reference it.
- **KDE compositor**: detect via `os.environ.get("XDG_CURRENT_DESKTOP","").upper() == "KDE"`. Skip silently elsewhere (Mutter on GNOME always composites — no user-level toggle).
- **CPU governor**: prefer `powerprofilesctl` (GNOME/systemd power-profiles-daemon, user-level). Fall back to `pkexec cpupower frequency-set -g performance` only if `pkexec` is available AND a sudoers rule permits it without password (detect via a dry `pkexec --version` probe); otherwise the switch stays available in config but runtime logs "skipped, no user-level path" rather than prompting. No password prompts mid-launch.
- **Kill processes**: `pkill -x <name>` per entry, argv-style (no shell). Validate names against `[A-Za-z0-9._-]+` before invoking; reject (and log) anything else.
- **Best-effort throughout**: toggle failure logs and continues. Only the escape-hatch `pre_launch_cmd` aborts on non-zero rc.

### Modified files
- `exwin/backend/app_config.py` — add `HookConfig` + `hooks` field + `[hooks]` TOML round-trip.
- `exwin/backend/launcher.py`:
  - In `launch()`: build env, call `hooks.apply_pre_hooks(app_config.hooks, env, log)`, stash the returned `HookState` on the Launcher instance.
  - On `HookAbort` from `pre_launch_cmd`: synthesise a `CrashInfo` (abort reason + shell output) and fire `on_crash` (ties into §1). No game Popen.
  - In `_watch` after Popen exits: call `hooks.apply_post_hooks(..., state, rc, ...)`.
  - Export `EXWIN_ISO_MOUNT` into the game env when an ISO was successfully mounted.
- `exwin/ui/app_settings_dialog.py` — new "Hooks" group under Launch:
  - **Curated rows (top):**
    - EntryRow "Mount disc image": path + browse button (filter `*.iso *.cue *.bin *.img`); empty disables.
    - EntryRow "Kill these processes before launch": comma-separated names; placeholder `discord,steam,obs`.
    - SwitchRow "Suspend KDE compositor" — hidden when not in KDE.
    - SwitchRow "CPU performance governor" — disabled with tooltip "No user-level governor tool found" when `_governor_tool_available()` returns None.
  - **Collapsible "Advanced — custom shell" expander:**
    - `Gtk.TextView`: pre-launch shell (placeholder: `# runs after toggles. $EXWIN_ISO_MOUNT is set if an ISO was mounted.`)
    - `Gtk.TextView`: post-launch shell
    - SwitchRow "Run post-launch only on crash"
    - Warning label: "Runs under /bin/sh as your user. No sandbox — treat like launch_args."

### Order of operations

Pre-launch (sequential; toggle failures log and continue):
1. Mount ISO (exports `$EXWIN_ISO_MOUNT`)
2. Kill processes
3. Suspend compositor
4. Performance governor
5. `pre_launch_cmd` (failure aborts + fires `on_crash`)
6. Build + run game cmd

Post-launch (sequential, best-effort):
1. `post_launch_cmd` (gated by `post_launch_on_crash_only`; still runs while ISO mounted + compositor suspended so it can reference them)
2. Restore governor
3. Resume compositor
4. Unmount ISO
5. (Killed processes are not restarted — by design.)

### UX flow
1. User opens a game's Advanced settings → Hooks group.
2. Fills "Mount disc image": `/mnt/games/RA3.iso`; adds `discord,steam` to kill list; toggles "Suspend KDE compositor".
3. Saves.
4. On next launch: ISO mounted → processes killed → compositor suspended → game runs → on exit everything reverses.
5. A user with an unusual need (start a VPN, switch audio sink, etc.) drops into "Advanced — custom shell" without the toggle authors needing to care.

### Dependencies
- `udisks2` / `udisksctl` — for ISO toggle. Usually preinstalled on GNOME and KDE.
- `fuseiso` — optional fallback for ISO mount when udisks2 absent.
- `pkill` (procps) — ubiquitous.
- `qdbus` — required only for the KDE compositor toggle.
- `powerprofilesctl` — optional; gracefully degrades.

### Test plan
- `tests/test_hooks.py` (new):
  - `test_mount_iso_records_state` — mocked udisksctl returns loop device + mount point; `HookState.iso_*` populated; env has `EXWIN_ISO_MOUNT`.
  - `test_unmount_iso_reverses` — post-hook invokes the inverse udisksctl calls.
  - `test_kill_processes_validates_names` — names with shell metacharacters are rejected + logged.
  - `test_suspend_kde_compositor_gated_by_desktop` — non-KDE env → no-op, `compositor_was_active=False`.
  - `test_suspend_kde_compositor_records_prior_state` — KDE env → returns was_active True, resume called in post.
  - `test_governor_prefers_powerprofilesctl` — both tools present → powerprofilesctl chosen.
  - `test_governor_gracefully_disabled_when_no_tool` — neither available → logs "skipped"; state.prior_power_profile None; no password prompt.
  - `test_toggle_failure_logs_and_continues` — udisksctl returns non-zero → log entry, later toggles still run.
  - `test_pre_launch_cmd_failure_raises_hook_abort` — `pre_launch_cmd=exit 1` → `HookAbort`; launcher turns this into `on_crash`, no game Popen.
  - `test_post_launch_on_crash_only` — flag True + rc=0 → post shell skipped; rc=1 → run.
- `tests/test_app_config.py` — `HookConfig` round-trip through TOML (empty table omitted; non-defaults written).
- `tests/test_launcher.py` — `test_hooks_sequenced`: pre-hook sentinel exists before game Popen; post-hook runs after exit; `HookState` reversed.
- Manual: mount a real ISO, launch an older game that needs the disc; verify umount after exit.

### Security / sandbox notes
- Curated toggles use argv (no shell) for everything except the escape hatch. Validate ISO path (readable file) and process names (`[A-Za-z0-9._-]+`) before invoking subprocess.
- Escape-hatch shell: same trust model as `launch_args` and `env`. Document clearly.
- Flatpak: toggles need DBus access to `org.freedesktop.UDisks2` (ISO mount), `org.freedesktop.UPower.PowerProfiles` (governor), `org.kde.KWin` (compositor). Manifest additions tracked as an integration follow-up; document any toggles that no-op inside the sandbox in v1.

### Open questions
- Killed processes auto-restart on exit? No — Discord/Steam re-launch themselves from autostart; the rest was probably what the user wanted gone.
- Exit-early-on-toggle-failure switch? No — best-effort is the less-surprising default.
- Scope of curated list: ship the four above; hold for explicit user requests before adding more (audio sink switch, MangoHud config picker, VPN start). Each new toggle is a DE/distro testing burden.
- Ordering of ISO unmount vs post-launch shell: post-shell runs first so it can still read from the mount. Users who need the opposite can use the toggle alone + a pre-launch shell that also unmounts (idempotent).
- Flatpak manifest DBus/Talk perms: punt to a packaging integration task; note which toggles degrade to no-ops inside the sandbox until then.

---

## 5. Umu-launcher integration

### Goal
Replace the hand-rolled `STEAM_COMPAT_DATA_PATH` / `STEAM_COMPAT_CLIENT_INSTALL_PATH` / `SteamAppId=0` Proton invocation with `umu-run`, gaining:
- Canonical Proton entry point (tracks upstream fixes).
- ProtonFixes per-game lookup keyed by Steam AppID (we already store `steam_appid` from the ProtonDB feature).
- Fewer fragile env-var workarounds (e.g. the `SteamAppId=0` hack in commit `cbd9c11`).

### Data model
- `Config.use_umu: bool = True` — default enabled; silently no-ops when umu binary absent.
- `AppConfig.use_umu: bool | None = None` — per-app override (None = follow global).
- Reuses `apps.steam_appid` column (already added for ProtonDB).

### New module: `exwin/backend/umu.py`

```
def is_available() -> bool:
    return shutil.which("umu-run") is not None

def resolve_gameid(app: AppEntry) -> str:
    # steam_appid → str; None → "0" (ProtonFixes' default/generic path)
```

### Modified files
- `exwin/backend/config.py` — add `use_umu` field + TOML round-trip.
- `exwin/backend/app_config.py` — add optional `use_umu: bool | None` override.
- `exwin/backend/launcher.py::_build_command` + `_build_env`:
  - Branch: `umu_active = runtime.type == "proton" and config.use_umu and umu.is_available()` (plus per-app override).
  - When active:
    - cmd = `["umu-run", str(exe), *launch_args]`
    - env adds `GAMEID=<resolve_gameid(app)>`, `PROTONPATH=<runtime.path>`, `WINEPREFIX=<prefix>/pfx`
    - Drop `STEAM_COMPAT_DATA_PATH`, `STEAM_COMPAT_CLIENT_INSTALL_PATH`, `SteamAppId` (umu sets them).
  - Wine runtimes: untouched (umu is Proton-only).
  - Gamescope wrapping unaffected: `gamescope ... -- umu-run <exe>`.
- `exwin/ui/settings_page.py` — "Use umu-launcher when available" switch; status badge ("Found at /usr/bin/umu-run" / "Not installed — falling back to direct Proton").
- `exwin/ui/app_settings_dialog.py` — per-app tri-state combo (Default / On / Off).
- Flatpak manifest (`io.github.exwin.yml`): add `umu-launcher` module (Python script + a few supporting files). If bundling proves fiddly, start as a host dep and document.

### Subtleties
- `SteamAppId=0` workaround becomes redundant when umu active (ProtonFixes now drives fix selection). Preserve it on the non-umu path to avoid regressing the fix from `cbd9c11`.
- For GOG titles without a resolved Steam appid, `GAMEID=0` → ProtonFixes generic path. Encourage users to run a ProtonDB lookup first (already wired in AppDetailDialog) to populate `steam_appid`.
- umu version probing (`umu-run --version`): track a minimum if a real bug surfaces; otherwise skip.

### UX flow
Invisible by default. Settings page has a single row showing current state. When a user opens a game's Advanced settings, a read-only row reads "Using umu (GAMEID=374320)" or similar.

### Dependencies
- `umu-launcher` (>=1.1 preferred). PyPI name `umu-launcher`; some distros package it.
- Flatpak: bundle if feasible; otherwise document as a host dep.

### Test plan
- `tests/test_umu.py`:
  - `is_available` honours PATH.
  - `resolve_gameid` handles None + valid appid.
- `tests/test_launcher.py`:
  - `test_umu_cmd_proton` — umu mocked available, Proton runtime → cmd[0] == "umu-run", env has `GAMEID`, `PROTONPATH`, no `STEAM_COMPAT_*`.
  - `test_umu_disabled_falls_back` — `config.use_umu = False` → current direct-Proton cmd unchanged.
  - `test_umu_missing_binary_falls_back` — is_available False → direct path.
  - `test_umu_wine_runtime_unchanged` — umu not applied for Wine.
  - `test_umu_per_app_override_off` — `AppConfig.use_umu = False` beats config.
  - `test_umu_gamescope_wraps_umu` — gamescope prefix present, `--` then `umu-run …`.
- Manual: launch a known ProtonFixes title (e.g. Dark Souls III appid 374320) with umu active; verify fixes applied (UI/cutscenes behaviour).

### Open questions
- Bundle vs host dep for Flatpak — lean host-only first; bundle if install friction surfaces.
- Migration: on first run after this lands, show a one-time toast "umu-launcher detected and enabled by default — disable in Settings if you hit issues." Keeps the change visible without being disruptive.
- Interaction with the existing `WINE_WAYLAND_DRIVER` workflow (§3.7 in the exploration doc): umu respects standard Wine env, so no conflict.

---

## Suggested delivery order

1. **Crash detection** (§1) — standalone, amplifies everything in the previous batch.
2. **Folder import** (§2) — standalone, addresses an ongoing user pain point.
3. **Prefix upgrade** (§3) — tiny, complements the existing Rebuild Prefix button.
4. **Shell hooks** (§4) — self-contained; §1's `on_crash` plumbing is nice to have first (pre-hook failures reuse it).
5. **Umu-launcher** (§5) — most architectural; do last so the earlier features don't complicate the refactor.

## Cross-cutting notes

- **No DB migrations**: §5 reuses the `steam_appid` column added for ProtonDB; the other four don't touch the schema.
- **CLI parity** (`exwin/__main__.py`): `launch` subcommand must honour pre/post hooks (§4) and use umu (§5); `list` gains nothing. Crash-detect output prints to stderr in headless mode.
- **Flatpak manifest**: only §5 adds a dep.
- **Offline-first principle**: none of these five require network access. §5's ProtonFixes lookup reads from a bundled DB shipped with umu, not from the network at launch time.
