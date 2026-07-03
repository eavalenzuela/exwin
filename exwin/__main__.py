"""Entry point: python -m exwin  or  the 'exwin' console script."""

import argparse
import sys
from importlib.metadata import version as _pkg_version


def _get_version() -> str:
    try:
        return _pkg_version("exwin")
    except Exception:
        return "dev"


def main() -> None:
    parser = argparse.ArgumentParser(prog="exwin")
    parser.add_argument("--version", action="version", version=f"exwin {_get_version()}")
    parser.add_argument(
        "--launch",
        metavar="APP_ID",
        help="(legacy) Launch app headlessly (used by .desktop shortcuts)",
    )
    subs = parser.add_subparsers(dest="command")

    subs.add_parser("list", help="List installed games")

    p = subs.add_parser("info", help="Show details for a game")
    p.add_argument("app_id")

    p = subs.add_parser("launch", help="Launch a game headlessly")
    p.add_argument("app_id")

    p = subs.add_parser("remove", help="Remove from library")
    p.add_argument("app_id")
    p.add_argument("--delete-files", action="store_true", help="Also delete game files on disk")

    p = subs.add_parser("migrate", help="Move game data to storage root")
    p.add_argument("app_id")

    p = subs.add_parser("backup-saves", help="Backup save files for a game")
    p.add_argument("app_id")

    p = subs.add_parser("restore-saves", help="Restore save files for a game")
    p.add_argument("app_id")
    p.add_argument("--backup", metavar="PATH", help="Path to specific backup zip (default: newest)")

    p = subs.add_parser("backups", help="List save backups for a game")
    p.add_argument("app_id")

    # Unknown args are tolerated only on the GUI path (GTK/GApplication may
    # consume its own flags); for explicit subcommands a typo like
    # `--delete-file` must be an error, not a silent no-op.
    args, extra = parser.parse_known_args()
    if extra and (args.command or args.launch):
        parser.error(f"unrecognized arguments: {' '.join(extra)}")

    if args.launch:
        _headless_launch(args.launch)
    elif args.command == "list":
        _cmd_list()
    elif args.command == "info":
        _cmd_info(args.app_id)
    elif args.command == "launch":
        _headless_launch(args.app_id)
    elif args.command == "remove":
        _cmd_remove(args.app_id, getattr(args, "delete_files", False))
    elif args.command == "migrate":
        _cmd_migrate(args.app_id)
    elif args.command == "backup-saves":
        _cmd_backup_saves(args.app_id)
    elif args.command == "restore-saves":
        _cmd_restore_saves(args.app_id, getattr(args, "backup", None))
    elif args.command == "backups":
        _cmd_backups(args.app_id)
    else:
        from exwin.app import ExwinApp

        sys.exit(ExwinApp().run(sys.argv))


def _init() -> tuple:
    """Load config and init DB. Returns (config,)."""
    from exwin.backend.config import Config
    from exwin.db.schema import init_db

    config = Config.load()
    init_db(config.data_dir)
    return (config,)


def _headless_launch(app_id: str) -> None:
    import subprocess
    import time
    from datetime import UTC, datetime

    from exwin.backend.app_config import load_app_config
    from exwin.backend.crash_detect import read_log_tail
    from exwin.backend.hooks import HookAbort, apply_post_hooks, apply_pre_hooks
    from exwin.backend.launcher import Launcher, rotate_log
    from exwin.db.apps import get_app, update_last_launched, update_playtime
    from exwin.db.runtimes import get_runtime

    (config,) = _init()

    app = get_app(app_id)
    if not app:
        sys.exit(f"exwin: app '{app_id}' not found in library")

    runtime = get_runtime(app.runtime_id) if app.runtime_id else None
    if not runtime:
        sys.exit(f"exwin: no runtime configured for '{app_id}'")

    app_config = load_app_config(app_id, config)
    launcher = Launcher(config)
    cmd = launcher.build_command(app, runtime, app_config)
    env = launcher.build_env(app, runtime, app_config)

    log_path = config.logs_dir / f"{app_id}.log"
    rotate_log(log_path)
    log_file = open(log_path, "w")  # noqa: SIM115

    def _hook_log(msg: str) -> None:
        log_file.write(f"{msg}\n")
        log_file.flush()

    # Mirror the GUI launch path: pre-hooks may mutate env (e.g. ISO mount);
    # a failing pre_launch_cmd aborts the launch.
    try:
        hook_state = apply_pre_hooks(app_config.hooks, env, _hook_log)
    except HookAbort as abort:
        log_file.close()
        print(f"exwin: launch aborted — {abort.reason}", file=sys.stderr)
        if abort.output:
            print(abort.output, file=sys.stderr)
        sys.exit(1)

    start_time = time.monotonic()
    rc = -1
    try:
        proc = subprocess.Popen(cmd, env=env, stdout=log_file, stderr=log_file)
        rc = proc.wait()
    finally:
        duration = time.monotonic() - start_time
        try:
            apply_post_hooks(app_config.hooks, hook_state, rc, env, _hook_log)
        except Exception as exc:  # noqa: BLE001 — post-hooks are best-effort
            _hook_log(f"hook: apply_post_hooks raised: {exc}")
        log_file.close()
    update_playtime(app_id, int(duration))
    update_last_launched(app_id, datetime.now(tz=UTC).isoformat())

    # Short-run crash: mirror the GUI's crash-detect threshold to stderr so
    # .desktop shortcut users see something actionable instead of a silent fail.
    if rc != 0 and duration < config.crash_threshold_seconds:
        tail = read_log_tail(log_path)
        print(
            f"exwin: '{app.name}' exited after {duration:.1f}s with rc={rc}.",
            file=sys.stderr,
        )
        print(f"exwin: log at {log_path}", file=sys.stderr)
        if tail:
            print("---- log tail ----", file=sys.stderr)
            print(tail, file=sys.stderr)
        sys.exit(rc)


def _cmd_list() -> None:
    from exwin.util import fmt_playtime

    (config,) = _init()

    from exwin.db.apps import get_all_apps

    apps = get_all_apps()
    if not apps:
        print("No games installed.")
        return

    col_id = max(len(a.app_id) for a in apps)
    col_name = max(len(a.name) for a in apps)
    col_src = max(len(a.source) for a in apps)

    header = f"{'ID':<{col_id}}  {'Name':<{col_name}}  {'Source':<{col_src}}  Playtime"
    print(header)
    print("-" * len(header))
    for a in sorted(apps, key=lambda x: x.name.lower()):
        pt = fmt_playtime(a.playtime_seconds) if a.playtime_seconds > 0 else "—"
        print(f"{a.app_id:<{col_id}}  {a.name:<{col_name}}  {a.source:<{col_src}}  {pt}")


def _cmd_info(app_id: str) -> None:
    from exwin.backend.app_config import load_app_config
    from exwin.db.apps import get_app
    from exwin.db.runtimes import get_runtime
    from exwin.util import fmt_playtime

    (config,) = _init()

    app = get_app(app_id)
    if not app:
        sys.exit(f"exwin: app '{app_id}' not found in library")

    runtime = get_runtime(app.runtime_id) if app.runtime_id else None
    app_config = load_app_config(app_id, config)

    def _row(label: str, value: str) -> None:
        print(f"{label:<14} {value}")

    _row("Name", app.name)
    _row("ID", app.app_id)
    _row("Source", app.source)
    _row("Install path", str(app.install_path) if app.install_path else "—")
    _row("Prefix", str(app.prefix_path) if app.prefix_path else "—")
    _row("Executable", app.exe_path or "—")
    _row("Runtime", runtime.name if runtime else "— (first detected)")
    _row("Playtime", fmt_playtime(app.playtime_seconds) if app.playtime_seconds else "—")
    _row("Last played", app.last_launched or "never")
    _row("Installed", app.install_date or "—")
    if app.tags:
        _row("Tags", ", ".join(app.tag_list))
    if app.steam_appid:
        _row("Steam AppID", str(app.steam_appid))
    if app.protondb_tier:
        _row("ProtonDB", app.protondb_tier)

    print()
    print("Config:")
    _row("  Arch", app_config.arch)
    _row("  DXVK", "yes" if app_config.dxvk else "no")
    _row("  VKD3D", "yes" if app_config.vkd3d else "no")
    if app_config.winetricks_verbs:
        _row("  Winetricks", " ".join(app_config.winetricks_verbs))
    if app_config.launch_args:
        _row("  Launch args", " ".join(app_config.launch_args))
    if app_config.env:
        _row("  Env vars", ", ".join(sorted(app_config.env)))
    if app_config.cpu_affinity:
        _row("  CPU affinity", app_config.cpu_affinity)
    if app_config.locale:
        _row("  Locale", app_config.locale)
    if app_config.save_path:
        _row("  Save path", app_config.save_path)


def _cmd_backups(app_id: str) -> None:
    from datetime import datetime

    from exwin.backend.saves import list_backups
    from exwin.db.apps import get_app

    (config,) = _init()

    app = get_app(app_id)
    if not app:
        sys.exit(f"exwin: app '{app_id}' not found in library")

    backups = list_backups(app_id, config)
    if not backups:
        print(f"No save backups for '{app_id}'.")
        return

    print(f"{len(backups)} backup(s) for '{app_id}' (newest first):")
    for b in backups:
        try:
            size_kib = b.stat().st_size / 1024
        except OSError:
            size_kib = 0.0
        # Filenames are UTC timestamps: 20260703T101500_123456Z.zip
        stamp = b.stem
        try:
            when = datetime.strptime(stamp, "%Y%m%dT%H%M%S_%fZ").strftime("%Y-%m-%d %H:%M:%S UTC")
        except ValueError:
            when = stamp
        print(f"  {b.name}  {when}  {size_kib:.1f} KiB")


def _cmd_remove(app_id: str, delete_files: bool) -> None:
    (config,) = _init()

    from exwin.db.apps import get_app

    app = get_app(app_id)
    if not app:
        sys.exit(f"exwin: app '{app_id}' not found in library")

    from exwin.backend.uninstall import uninstall_app

    uninstall_app(app, config, delete_files, on_progress=print)


def _cmd_migrate(app_id: str) -> None:
    (config,) = _init()

    from exwin.db.apps import get_app

    app = get_app(app_id)
    if not app:
        sys.exit(f"exwin: app '{app_id}' not found in library")

    if not config.storage_root:
        sys.exit("exwin: storage_root is not configured — set it in Settings first")

    from exwin.backend.migrate import move_game_data

    try:
        new_app = move_game_data(app, config, on_progress=print)
        print(f'"{new_app.name}" moved to {config.storage_root}')
    except Exception as exc:
        sys.exit(f"exwin: migration failed: {exc}")


def _cmd_backup_saves(app_id: str) -> None:
    (config,) = _init()

    from exwin.backend.app_config import load_app_config
    from exwin.backend.saves import backup_saves, enforce_retention
    from exwin.db.apps import get_app

    app = get_app(app_id)
    if not app:
        sys.exit(f"exwin: app '{app_id}' not found in library")

    app_config = load_app_config(app_id, config)
    if not app_config.save_path:
        sys.exit(f"exwin: no save path configured for '{app_id}'")

    try:
        dest = backup_saves(app, app_config, config)
        removed = enforce_retention(app_id, config)
        print(f"Saves backed up to: {dest}")
        if removed:
            print(f"  ({len(removed)} old backup(s) pruned)")
    except Exception as exc:
        sys.exit(f"exwin: backup failed: {exc}")


def _cmd_restore_saves(app_id: str, backup_path_str: str | None) -> None:
    from pathlib import Path

    (config,) = _init()

    from exwin.backend.app_config import load_app_config
    from exwin.backend.saves import list_backups, restore_saves
    from exwin.db.apps import get_app

    app = get_app(app_id)
    if not app:
        sys.exit(f"exwin: app '{app_id}' not found in library")

    app_config = load_app_config(app_id, config)
    if not app_config.save_path:
        sys.exit(f"exwin: no save path configured for '{app_id}'")

    if backup_path_str:
        backup_path = Path(backup_path_str)
        if not backup_path.exists():
            sys.exit(f"exwin: backup file not found: {backup_path}")
    else:
        backups = list_backups(app_id, config)
        if not backups:
            sys.exit(f"exwin: no backups found for '{app_id}'")
        backup_path = backups[0]

    try:
        restore_saves(backup_path, app_config)
        print(f"Saves restored from: {backup_path}")
    except Exception as exc:
        sys.exit(f"exwin: restore failed: {exc}")


if __name__ == "__main__":
    main()
