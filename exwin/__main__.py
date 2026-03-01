"""Entry point: python -m exwin  or  the 'exwin' console script."""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="exwin")
    parser.add_argument(
        "--launch",
        metavar="APP_ID",
        help="Launch app headlessly (used by .desktop shortcuts)",
    )
    args, _ = parser.parse_known_args()

    if args.launch:
        _headless_launch(args.launch)
    else:
        from exwin.app import ExwinApp

        sys.exit(ExwinApp().run(sys.argv))


def _headless_launch(app_id: str) -> None:
    import os

    from exwin.backend.app_config import load_app_config
    from exwin.backend.config import Config
    from exwin.backend.launcher import Launcher
    from exwin.db.apps import get_app
    from exwin.db.runtimes import get_runtime
    from exwin.db.schema import init_db

    config = Config.load()
    init_db(config.data_dir)

    app = get_app(app_id)
    if not app:
        sys.exit(f"exwin: app '{app_id}' not found in library")

    runtime = get_runtime(app.runtime_id) if app.runtime_id else None
    if not runtime:
        sys.exit(f"exwin: no runtime configured for '{app_id}'")

    app_config = load_app_config(app_id, config)
    launcher = Launcher(config)
    cmd = launcher._build_command(app, runtime, app_config)
    env = launcher._build_env(app, runtime, app_config)

    os.execvpe(cmd[0], cmd, env)


if __name__ == "__main__":
    main()
