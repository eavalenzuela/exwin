"""Entry point: python -m exwin  or  the 'exwin' console script."""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="exwin")
    parser.add_argument(
        "--launch",
        metavar="APP_ID",
        help="(legacy) Launch app headlessly (used by .desktop shortcuts)",
    )
    subs = parser.add_subparsers(dest="command")

    subs.add_parser("list", help="List installed games")

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

    args, _ = parser.parse_known_args()

    if args.launch:
        _headless_launch(args.launch)
    elif args.command == "list":
        _cmd_list()
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
    from exwin.backend.launcher import Launcher
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
    log_file = open(log_path, "w")  # noqa: SIM115

    start_time = time.monotonic()
    proc = subprocess.Popen(cmd, env=env, stdout=log_file, stderr=log_file)
    proc.wait()
    log_file.close()
    elapsed = int(time.monotonic() - start_time)
    update_playtime(app_id, elapsed)
    update_last_launched(app_id, datetime.now(tz=UTC).isoformat())


def _cmd_list() -> None:
    from exwin.ui.library_page import _fmt_playtime

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
        pt = _fmt_playtime(a.playtime_seconds) if a.playtime_seconds > 0 else "—"
        print(f"{a.app_id:<{col_id}}  {a.name:<{col_name}}  {a.source:<{col_src}}  {pt}")


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
    from exwin.backend.saves import backup_saves
    from exwin.db.apps import get_app

    app = get_app(app_id)
    if not app:
        sys.exit(f"exwin: app '{app_id}' not found in library")

    app_config = load_app_config(app_id, config)
    if not app_config.save_path:
        sys.exit(f"exwin: no save path configured for '{app_id}'")

    try:
        dest = backup_saves(app, app_config, config)
        print(f"Saves backed up to: {dest}")
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
