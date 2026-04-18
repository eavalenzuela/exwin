"""Crash / short-run detection for launched apps.

When a game exits quickly with a non-zero return code, the Launcher synthesises
a :class:`CrashInfo` and fires ``on_crash`` so the UI (or CLI) can surface the
log tail and offer actionable next steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exwin.backend.runtime import Runtime
from exwin.models import AppEntry

_DEFAULT_TAIL_LINES = 40


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
    """Return the last *tail_lines* lines of *log_path*, or an empty string."""
    try:
        text = log_path.read_text(errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[-tail_lines:])
