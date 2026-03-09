# exwin TODO

## Code Quality & Robustness

### High Priority

- [x] **Thread safety in Launcher** — `launcher.py`: `_running` dict now guarded by `threading.Lock`.
- [x] **Zip/tar extraction path traversal** — `saves.py` and `dxvk.py` now validate all archive member paths stay within target directory before extracting.
- [x] **Headless launch uses private API** — `Launcher` now exposes `build_command()` and `build_env()` public methods; `__main__.py` uses them.
- [x] **Duplicate uninstall logic** — Extracted to `backend/uninstall.py`; both `window.py` and `__main__.py` now use `uninstall_app()`.
- [ ] **Fragile DB migration** — `schema.py:49-53` uses bare `ALTER TABLE ADD COLUMN` in try/except. Add a `_migrations` table with numbered migration functions for future-proofing.
- [x] **No PRAGMA busy_timeout** — Added `PRAGMA busy_timeout = 5000` in `get_conn()`.

### Medium Priority

- [x] **Headless launch doesn't write to log file** — Now writes stdout/stderr to `logs/<app_id>.log`.
- [x] **Race in `_watch()` + `stop()`** — `_watch()` now checks `was_tracked` after pop; skips playtime/callback if already removed.
- [ ] **Magic strings for source/type** — `"gog"`, `"manual"`, `"proton"`, `"wine"` scattered as raw strings. Use `StrEnum` to catch typos and improve IDE support.
- [ ] **Path type inconsistency** — Some functions return `str` (AppEntry, DB), others return `Path` (Config, backend). Standardize on `Path` internally, convert to `str` only at DB boundary.
- [x] **Blocking operations on GTK main thread** — Shortcut creation, save backup, and restore now run in background threads with button disable/re-enable.
- [ ] **No Proton-GE SHA512 verification** — `proton_ge.py` downloads `.tar.gz` without checking the `.sha512sum` asset. VKD3D-Proton tarballs also have no integrity check.
- [x] **No exe_path validation at launch time** — `_build_command()` now raises `FileNotFoundError` with a clear message if the exe doesn't exist.
- [x] **Cover art error CSS not cleared** — `"error"` CSS class now removed from cover row before retrying save.

### Low Priority

- [ ] **Regex patterns not compiled** — `gog_installer.py` uses `re.search`/`re.match` in loops without precompilation.
- [ ] **File descriptor leak in launcher** — `launcher.py:62` opens log_file in `launch()`, closed in `_watch()` on daemon thread. If thread dies, file never closes.
- [ ] **`install_dialog.py` is 784 lines** — Largest file by far. GOG flow and generic Wine flow share a dialog but have different state machines. Split into separate modules or extract page builders.
- [ ] **Config._ensure_dirs() silently skips storage root** — If external drive is unmounted, later code still assumes `installs_dir` is writable. Should warn or error.

---

## Features

### High Value / Moderate Effort

- [x] **Per-app runtime selection in UI** — AppSettingsDialog now has a Runtime ComboRow; saves to DB via `update_runtime()`.
- [x] **Library sorting & filtering** — Sort dropdown (name, last played, playtime, install date), ascending/descending toggle, and source filter (All/GOG/Manual) added to LibraryPage.
- [x] **"Add Existing Game" flow** — AddExistingDialog: pick directory + pick exe + pick runtime → create prefix + DB entry. "+" button in window header.
- [x] **Log viewer** — LogViewerDialog: monospace scrollable text view. "View Log" button in AppDetailDialog (shown when log file exists).
- [x] **Wine prefix tools** — Prefix Tools group in AppDetailDialog with winecfg, regedit, Kill Prefix buttons. Backend `prefix_tools.py` handles env setup for both Proton and Wine.

### Medium Value / Low Effort

- [x] **Keyboard shortcuts** — Ctrl+F (search focus), Ctrl+Q (quit) via `Gio.SimpleAction` + `set_accels_for_action` in `app.py`.
- [x] **Disk space display** — Install size and disk free shown on AppDetailDialog info group. Free space on target shown in migration confirmation dialog.
- [x] **Desktop notification on game exit** — `Gio.Notification` sent in `_on_app_exited` (window.py) when a game process ends.
- [x] **`--version` CLI flag** — `parser.add_argument("--version", ...)` using `importlib.metadata.version("exwin")`.
- [x] **Backup retention policy** — `Config.backup_max_count` (default 5, 0=unlimited); `enforce_retention()` in `saves.py` called after every backup (UI + CLI). SpinRow in SettingsPage.
- [x] **Automatic save path detection** — "Detect" button in AppSettingsDialog scans Wine prefix user dirs (AppData, Documents/My Games, Saved Games) and install dir for save/saves subdirs. `backend/save_detect.py`.

### Lower Priority / Bigger Scope

- [x] **Library categories/tags** — `tags` TEXT column in DB (comma-separated), `tag_list` property on AppEntry, tag editor (EntryRow + save button) in AppDetailDialog, tag filter dropdown in LibraryPage header. `update_tags()` and `get_all_tags()` in db/apps.py.
- [x] **Install progress bar** — `count_files()` in `gog_installer.py` pre-counts files via `innoextract --list`. `Gtk.ProgressBar` on installing page shows `current / total files`. Progress callback threaded through `install_worker.py` → `install_dialog.py`.
- [x] **Drag-and-drop installer** — `Gtk.DropTarget` on LibraryPage accepts `.exe` files. Dropped file opens `InstallDialog` with `initial_installer` param, auto-starts probing.
- [x] **Window state persistence** — `Config.window_width/height/sidebar_visible` saved to `[window]` TOML table. Loaded on window creation, saved on `close-request` via `save_window_state()`.
- [x] **Flatpak-aware runtime detection** — `runtime.py` now scans `~/.var/app/com.valvesoftware.Steam/data/Steam/{steamapps/common,compatibilitytools.d}` in addition to native Steam paths.
- [ ] **Import Lutris/Heroic/Bottles configs** — Parse existing launcher databases and import games as library entries.
- [ ] **Controller/gamepad navigation** — Gamepad-friendly UI navigation for couch use.
- [ ] **Plugin/hook system** — Custom pre/post install scripts per game.

---

## UI / UX

- [x] **No input validation on text fields** — `_validate()` in AppSettingsDialog checks env vars and DLL overrides for KEY=VALUE format, winetricks verbs for valid characters. Toast shown on first error.
- [x] **No unsaved changes warning** — AppSettingsDialog tracks dirty state via `_snapshot()`; `close-attempt` handler shows discard confirmation if fields changed.
- [x] **Dialog sizing on small screens** — Removed hardcoded `content_height` from AppDetailDialog and AppSettingsDialog; dialogs now size to content.
- [x] **Sidebar not responsive** — Sidebar auto-collapses when window width < 500px via `notify::default-width` handler.
- [x] **No step indicator in install wizard** — `_set_step()` helper updates `Adw.WindowTitle` subtitle with "Step N of 4" at each page transition.
- [x] **Missing accessibility** — Added `Gtk.AccessibleProperty.LABEL` on cover art images in both library cards and detail dialog.
- [x] **Exe selection skipped** — `_on_wine_installer_done` now shows exe selection page when >1 candidate found, with best guess pre-selected.
- [x] **AppDetailDialog doesn't refresh live** — `GLib.timeout_add_seconds(2)` polls `launcher.is_running()` and updates running indicator, primary button, and uninstall sensitivity.

---

## Test Coverage

### Critical (untested core paths)

- [x] **`gog_installer.py`** — 22 tests: _parse_info_output, find_primary_exe, guess_exe, parse_game_info, find_sibling_parts, validate_checksums, app_id_from_info, find_cover_art.
- [x] **`install_worker.py`** — 3 tests: full install_gog pipeline with mocked innoextract/extract, already-installed check, install_gog_dlc.
- [x] **`launcher.py`** — 11 tests: build_command (Proton/Wine/args/gamemode/mangohud/missing exe), build_env (Proton/Wine/arch/DLL/GPU/user env), lifecycle.
- [x] **`runtime.py`** — 10 tests: Runtime dataclass, _read_proton_version, _read_wine_version, scan_runtimes (Proton dirs, system Wine, dedup).
- [x] **`prefix.py`** — 8 tests: prefix_root, wineprefix_path (Proton pfx/ vs Wine root), create_prefix (Proton/Wine/arch), delete_prefix.

### Important (untested supporting modules)

- [x] **`generic_installer.py`** — 11 tests: detect_installer_type, scan_candidate_exes (skip dirs/exes, Proton layout), pick_best_exe, _slugify_app_id.
- [x] **`winetricks.py`** — 7 tests: is_available, run_verbs (Wine/Proton env setup, unattended flag, error cases).
- [x] **`gpu.py`** — 7 tests: _is_gpu_class, _parse_lspci (GPU/audio/timeout/last stanza), GPU dataclass, vendor map.
- [x] **`dxvk.py`** — 8 tests: install_dxvk (winetricks calls, error, progress), _find_tarball_asset, _find_setup_script, install_vkd3d (fallback).
- [x] **`proton_ge.py`** — 5 tests: find_ge_proton_asset (tar.gz/sha512/missing), is_installed, download_and_install (progress, already installed).
- [x] **`tray.py`** — 14 tests: TrayIcon construction, SNI properties (Id/Category/Title/Icon/Menu/unknown), menu properties, layout, method calls (Activate/SecondaryActivate), start failure.
- [x] **`db/runtimes.py`** — 9 tests: upsert_runtime (insert/update/different paths), get_runtime, get_all_runtimes, sync_runtimes (idempotent, preserves fields).

### Dev Tooling

- [ ] **Add pytest-cov** — No coverage measurement exists. Add to pyproject.toml and pytest config.
- [ ] **Set up GitHub Actions CI** — Run pytest + ruff check + coverage on push/PR.
- [ ] **Add pre-commit hooks** — Enforce ruff format/check before commit.
- [ ] **Add type checking** — Configure mypy or pyright; complex code (launcher, GLib integration) benefits most.
- [ ] **Declare test dependencies** — pytest not listed in pyproject.toml; add `[project.optional-dependencies]` dev extras.
