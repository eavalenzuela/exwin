"""Small shared helpers with no GTK dependency.

Anything imported by both the CLI (`exwin.__main__`) and the UI belongs here so
that headless CLI invocations never pull in gi/GTK.
"""

from __future__ import annotations

import subprocess


def tool_usable(path: str) -> bool:
    """True if the executable at *path* actually runs in this environment.

    A binary can be on PATH yet not runnable: a host tool reached through a
    Flatpak sandbox (``/run/host/usr/bin``) whose shared libraries are not in
    the runtime, or a wrapper script whose target is outside the sandbox.
    Both fail with exit code 127 without doing any work, so a cheap spawn
    check here lets callers fall through to the next candidate (or warn up
    front) instead of failing mid-extraction.
    """
    try:
        proc = subprocess.run(
            [path, "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return True  # slow, but it executed
    except OSError:
        return False
    return proc.returncode != 127


def fmt_playtime(seconds: int) -> str:
    """Format a playtime in seconds as a compact human string (e.g. "3h 12m")."""
    if seconds < 60:
        return "< 1m"
    h, m = divmod(seconds // 60, 60)
    return f"{h}h {m}m" if h else f"{m}m"
