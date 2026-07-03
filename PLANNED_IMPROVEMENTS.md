# Planned Improvements & Features

Plan for the 2026-07-03 improvement pass. Item references (§) point at
`functionality_exploration.md`.

## Improvements (existing behaviour / robustness / UX / docs)

1. **Stop kills the whole process group** — `Launcher.stop()` only SIGTERMs the
   direct child, but `start_new_session=True` + Proton/umu/gamescope wrappers
   mean the actual game keeps running; signal the process group instead.
2. **Headless launches honour pre/post-launch hooks** — `.desktop` shortcut
   launches (`exwin launch <id>`) currently skip ISO mount / kill-list /
   governor hooks that the GUI applies; parity bug.
3. **Decouple the CLI from GTK** — `exwin list` imports
   `exwin.ui.library_page` (→ gi/GTK) just for `_fmt_playtime`; move the
   formatter to a new GTK-free `exwin/util.py` so the CLI works headless.
4. **Survive a corrupt `config.toml`** — a truncated/garbled global config
   currently crashes startup with `TOMLDecodeError`; back the bad file up to
   `config.toml.bad` and continue with defaults.
5. **Launch log rotation** — each launch truncates `<id>.log`, destroying the
   evidence of the previous crash; keep one generation as `<id>.log.1`.
6. **Bound crash-log tail reads** — `read_log_tail()` slurps the whole file;
   a multi-GB `WINEDEBUG` log would OOM the crash dialog. Read only the last
   64 KiB.
7. **Strict CLI argument validation** — `parse_known_args()` silently ignores
   typos like `--delete-file`; error out on unrecognised args when a
   subcommand is given (still tolerant for the GTK passthrough path).
8. **README data-layout fix** — README documents `~/.local/share/exwin/`, but
   the actual default is `~/.exwin/` (see `_DEFAULT_DATA_DIR` and the tests
   that assert it); also document the `EXWIN_DATA_DIR` override.
9. **Stop a running game before uninstalling it** — the GUI uninstall path
   leaves the game process running and untracked; stop it first.
10. **Library search matches tags** — the search box only filters on name;
    make it also match the per-app tag list (e.g. "rpg").

## New features

11. **Wine sync / NVAPI / locale env knobs (§3.1, §3.5, §3.9, §3.10)** —
    per-app tri-state ESYNC/FSYNC toggles (WINEESYNC/WINEFSYNC vs
    PROTON_NO_ESYNC/PROTON_NO_FSYNC), NVAPI/DLSS passthrough
    (PROTON_ENABLE_NVAPI + DXVK_ENABLE_NVAPI), locale override (LANG/LC_ALL
    for region-locked titles), and per-app DXVK state cache dir
    (DXVK_STATE_CACHE_PATH under the prefix); TOML round-trip + settings UI.
12. **Sleep/idle inhibit during play (§6.1)** — wrap launches in
    `systemd-inhibit --what=idle:sleep` so long cutscenes/controller sessions
    don't suspend the machine; global toggle in Settings, graceful skip when
    systemd-inhibit is absent.
13. **CPU affinity / thread cap (§3.8)** — per-app `taskset -c <spec>` wrapper
    for ancient titles that break on high core counts; validated cpu-list
    entry in the app settings dialog.
14. **CLI `info` and `backups` subcommands** — `exwin info <id>` prints paths,
    runtime, playtime, ProtonDB tier and config summary; `exwin backups <id>`
    lists save backups with timestamp + size (pairs with
    backup-saves/restore-saves).
15. **Windows `.lnk` shortcut resolution (§1.6)** — minimal [MS-SHLLINK]
    parser (`backend/lnk.py`) for LocalBasePath + RelativePath; folder import
    resolves `.lnk` stubs GOG installers leave behind and promotes their
    targets to the top of the exe candidate list.
