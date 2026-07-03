"""Crash / short-run detection for launched apps.

When a game exits quickly with a non-zero return code, the Launcher synthesises
a :class:`CrashInfo` and fires ``on_crash`` so the UI (or CLI) can surface the
log tail and offer actionable next steps.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from exwin.backend.runtime import Runtime
from exwin.models import AppEntry

_DEFAULT_TAIL_LINES = 40

# Never read more than this many bytes when tailing a log — a WINEDEBUG log
# can grow to gigabytes and would otherwise get slurped whole into memory.
_MAX_TAIL_BYTES = 64 * 1024


@dataclass
class CrashInfo:
    app: AppEntry
    rc: int
    duration_seconds: float
    log_tail: str
    log_path: Path
    runtime: Runtime | None
    reason: str = ""  # free-form; set for pre-hook-abort-style synthetic crashes


def build_crash_info(
    app: AppEntry,
    rc: int,
    duration_seconds: float,
    log_path: Path,
    runtime: Runtime | None,
    tail_lines: int = _DEFAULT_TAIL_LINES,
    reason: str = "",
) -> CrashInfo:
    """Assemble a :class:`CrashInfo` from a short-run exit event."""
    return CrashInfo(
        app=app,
        rc=rc,
        duration_seconds=duration_seconds,
        log_tail=read_log_tail(log_path, tail_lines),
        log_path=log_path,
        runtime=runtime,
        reason=reason,
    )


def read_log_tail(log_path: Path, tail_lines: int = _DEFAULT_TAIL_LINES) -> str:
    """Return the last *tail_lines* lines of *log_path*, or an empty string.

    Reads at most the final :data:`_MAX_TAIL_BYTES` of the file, so tailing a
    multi-gigabyte Wine log stays cheap.
    """
    try:
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - _MAX_TAIL_BYTES))
            data = f.read(_MAX_TAIL_BYTES)
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    # If we started mid-file, the first line is almost certainly partial.
    if size > _MAX_TAIL_BYTES and len(lines) > tail_lines:
        lines = lines[1:]
    return "\n".join(lines[-tail_lines:])
