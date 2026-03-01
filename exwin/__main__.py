"""Entry point: python -m exwin  or  the 'exwin' console script."""

import sys

from exwin.app import ExwinApp


def main() -> None:
    app = ExwinApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
