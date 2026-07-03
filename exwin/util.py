"""Small shared helpers with no GTK dependency.

Anything imported by both the CLI (`exwin.__main__`) and the UI belongs here so
that headless CLI invocations never pull in gi/GTK.
"""

from __future__ import annotations


def fmt_playtime(seconds: int) -> str:
    """Format a playtime in seconds as a compact human string (e.g. "3h 12m")."""
    if seconds < 60:
        return "< 1m"
    h, m = divmod(seconds // 60, 60)
    return f"{h}h {m}m" if h else f"{m}m"
