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
- [ ] **Library sorting & filtering** — Grid only supports name search. Add sort dropdown (name, last played, playtime, install date) and source filter (All/GOG/Manual).
- [ ] **"Add Existing Game" flow** — Register an already-installed game without re-running an installer. Dialog: pick directory + pick exe + pick runtime → create prefix reference + DB entry.
- [ ] **Log viewer** — Logs go to `~/.exwin/logs/<app_id>.log` but aren't accessible from GUI. Add "View Log" button in AppDetailDialog.
- [ ] **Wine prefix tools** — Buttons in AppDetailDialog/AppSettingsDialog for:
  - Run winecfg (with correct WINEPREFIX)
  - Run regedit
  - Kill prefix processes (`wineserver -k`)
  - Quick winetricks verb entry

### Medium Value / Low Effort

- [ ] **Keyboard shortcuts** — No shortcuts exist. Add Ctrl+F (search), Ctrl+Q (quit), Escape (close dialog) via `Gtk.ShortcutController`.
- [ ] **Disk space display** — Show install size on AppDetailDialog. Show free space on target drive during install/migration.
- [ ] **Desktop notification on game exit** — Fire `Gio.Notification` when a game exits (especially headless). One `send_notification()` call in `_on_app_exited`.
- [ ] **`--version` CLI flag** — Add `parser.add_argument("--version", action="version", version=...)`.
- [ ] **Backup retention policy** — `saves.py` creates unlimited timestamped backups. Add configurable max count (e.g., keep last 5).
- [ ] **Automatic save path detection** — "Detect" button that scans common locations:
  - `<prefix>/pfx/drive_c/users/steamuser/AppData/`
  - `<prefix>/drive_c/users/*/My Documents/My Games/`
  - Inside the install directory

### Lower Priority / Bigger Scope

- [ ] **Library categories/tags** — `tags` column in DB + tag editor in AppDetailDialog + filter dropdown in library header.
- [ ] **Install progress bar** — Parse `innoextract` file count output for a percentage estimate instead of unbounded log scroll.
- [ ] **Drag-and-drop installer** — Allow dropping `.exe` onto library page to start install flow.
- [ ] **Window state persistence** — Save window size, sidebar visibility, search state across sessions.
- [ ] **Flatpak-aware runtime detection** — `runtime.py` only scans `~/.steam/root/`. Under Flatpak, Steam lives at `~/.var/app/com.valvesoftware.Steam/...`.
- [ ] **Import Lutris/Heroic/Bottles configs** — Parse existing launcher databases and import games as library entries.
- [ ] **Controller/gamepad navigation** — Gamepad-friendly UI navigation for couch use.
- [ ] **Plugin/hook system** — Custom pre/post install scripts per game.

---

## UI / UX

- [ ] **No input validation on text fields** — AppSettingsDialog env vars/DLL overrides accept invalid KEY=VALUE; winetricks verbs not checked; storage_root path not validated writable.
- [ ] **No unsaved changes warning** — AppSettingsDialog can be closed without saving; no confirmation dialog.
- [ ] **Dialog sizing on small screens** — AppDetailDialog (440x560) and AppSettingsDialog (520x720) are too tall for 1024x768. Make dialogs adaptive.
- [ ] **Sidebar not responsive** — Fixed 180px width; unusable on narrow windows (<500px).
- [ ] **No step indicator in install wizard** — InstallDialog has multiple pages but no visible "Step 2 of 5" indicator.
- [ ] **Missing accessibility** — No mnemonics (Alt+Key), no focus management after page transitions, no accessible names on cover images.
- [ ] **Exe selection skipped** — `_on_wine_installer_done` goes straight to `pick_best_exe()` finalize. If best guess is wrong, user has no recourse during install. Should always show exe selection when >1 candidate.
- [ ] **AppDetailDialog doesn't refresh live** — Holds a snapshot of `is_running`; doesn't update if app launched/stopped from elsewhere.

---

## Test Coverage

### Critical (untested core paths)

- [ ] **`gog_installer.py`** — probe, extract, parse_game_info, find_primary_exe, guess_exe, validate_checksums, find_sibling_parts. Mock innoextract subprocess.
- [ ] **`install_worker.py`** — Full install_gog() pipeline, install_gog_dlc(). Integration tests with mocked installer.
- [ ] **`launcher.py`** — Process spawn, daemon thread cleanup, env building, GPU selection, GLib.idle_add callback.
- [ ] **`runtime.py`** — scan_runtimes() filesystem scanning, _read_proton_version, _read_wine_version. Mock filesystem.
- [ ] **`prefix.py`** — create_prefix (wineboot subprocess), delete_prefix, wineprefix_path for Proton vs Wine.

### Important (untested supporting modules)

- [ ] **`generic_installer.py`** — detect_installer_type, scan_candidate_exes, pick_best_exe, finalize_generic_install.
- [ ] **`winetricks.py`** — run_verbs env setup (Proton vs Wine paths), is_available.
- [ ] **`gpu.py`** — detect_gpus, _parse_lspci. Mock /sys/class/drm and lspci output.
- [ ] **`dxvk.py`** — install_dxvk, install_vkd3d. Mock winetricks and GitHub API.
- [ ] **`proton_ge.py`** — get_latest_release, download_and_install. Mock GitHub API.
- [ ] **`tray.py`** — TrayIcon start/stop, DBus method handlers. Mock Gio.DBus.
- [ ] **`db/runtimes.py`** — upsert_runtime, sync_runtimes.

### Dev Tooling

- [ ] **Add pytest-cov** — No coverage measurement exists. Add to pyproject.toml and pytest config.
- [ ] **Set up GitHub Actions CI** — Run pytest + ruff check + coverage on push/PR.
- [ ] **Add pre-commit hooks** — Enforce ruff format/check before commit.
- [ ] **Add type checking** — Configure mypy or pyright; complex code (launcher, GLib integration) benefits most.
- [ ] **Declare test dependencies** — pytest not listed in pyproject.toml; add `[project.optional-dependencies]` dev extras.
