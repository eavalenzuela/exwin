"""Pre-launch / post-launch hooks — curated toggles + shell escape hatch.

Two layers:

* **Curated toggles** (ISO mount, kill processes, KDE compositor suspend, CPU
  performance governor) that call out to argv-only helpers — no shell.
* **Shell escape hatch** — ``pre_launch_cmd`` and ``post_launch_cmd`` run under
  ``/bin/sh -c`` as the user. Failure of ``pre_launch_cmd`` aborts the launch
  via :class:`HookAbort`; ``post_launch_cmd`` is always best-effort.

Each toggle is best-effort: failures log and continue. Only the shell escape
hatch ``pre_launch_cmd`` short-circuits the launch.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from exwin.backend.app_config import HookConfig

Log = Callable[[str], None]

# Shell-metachar whitelist for process names passed to ``pkill -x``.
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class HookAbort(Exception):
    """Raised by :func:`apply_pre_hooks` when ``pre_launch_cmd`` exits non-zero.

    The caller (Launcher) converts this into a synthesised :class:`CrashInfo`
    so the crash dialog / CLI crash output can surface the abort reason.
    """

    def __init__(self, reason: str, output: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.output = output


@dataclass
class HookState:
    """Records what *actually* happened so post-hooks can reverse it."""

    iso_loop_device: str | None = None
    iso_mount_point: Path | None = None
    iso_fuse_mounted: bool = False  # True if fallback `fuseiso` was used
    compositor_was_active: bool = False
    prior_power_profile: str | None = None
    killed_processes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def apply_pre_hooks(hooks: HookConfig, env: dict[str, str], log: Log) -> HookState:
    """Run pre-launch hooks; mutate *env*; return the state for reversal.

    Order: mount ISO → kill processes → suspend compositor → performance
    governor → ``pre_launch_cmd``. Toggle failures log and continue; a
    non-zero ``pre_launch_cmd`` raises :class:`HookAbort`.
    """
    state = HookState()

    if hooks.mount_iso:
        _try_mount_iso(hooks.mount_iso, state, env, log)

    if hooks.kill_processes:
        state.killed_processes = _kill_processes(hooks.kill_processes, log)

    if hooks.suspend_kde_compositor:
        state.compositor_was_active = _suspend_kde_compositor(log)

    if hooks.cpu_performance_governor:
        state.prior_power_profile = _set_performance_governor(log)

    if hooks.pre_launch_cmd.strip():
        _run_pre_shell(hooks.pre_launch_cmd, env, log)

    return state


def apply_post_hooks(
    hooks: HookConfig,
    state: HookState,
    rc: int,
    env: dict[str, str],
    log: Log,
) -> None:
    """Reverse the curated toggles and (optionally) run ``post_launch_cmd``.

    Order: ``post_launch_cmd`` → restore governor → resume compositor →
    unmount ISO. Post-shell runs first so it can still read from the ISO
    mount and observe the suspended compositor state.
    Killed processes are *not* restarted — autostart apps self-recover and
    the rest was probably what the user wanted gone.
    """
    if hooks.post_launch_cmd.strip():
        _run_post_shell(hooks.post_launch_cmd, hooks.post_launch_on_crash_only, rc, env, log)

    if state.prior_power_profile is not None:
        _restore_governor(state.prior_power_profile, log)

    if state.compositor_was_active:
        _resume_kde_compositor(log)

    if state.iso_loop_device or state.iso_mount_point:
        _unmount_iso(state, log)


# ---------------------------------------------------------------------------
# ISO mount
# ---------------------------------------------------------------------------


def _try_mount_iso(iso_path: str, state: HookState, env: dict[str, str], log: Log) -> None:
    path = Path(iso_path)
    if not path.is_file():
        log(f"hook: mount ISO skipped — file not found: {path}")
        return
    try:
        loop, mount, is_fuse = _mount_iso(path, log)
    except Exception as exc:
        log(f"hook: mount ISO failed: {exc}")
        return
    state.iso_loop_device = loop
    state.iso_mount_point = mount
    state.iso_fuse_mounted = is_fuse
    env["EXWIN_ISO_MOUNT"] = str(mount)
    log(f"hook: mounted {path} at {mount}")


def _mount_iso(path: Path, log: Log) -> tuple[str, Path, bool]:
    """Mount *path*; return (loop_device, mount_point, is_fuseiso).

    Prefers ``udisksctl`` (user-level, DBus); falls back to ``fuseiso``.
    """
    if shutil.which("udisksctl"):
        setup = subprocess.run(
            ["udisksctl", "loop-setup", "--file", str(path), "--no-user-interaction"],
            capture_output=True,
            text=True,
            check=False,
        )
        if setup.returncode != 0:
            raise RuntimeError(
                f"udisksctl loop-setup: {setup.stderr.strip() or setup.stdout.strip()}"
            )
        loop = _parse_loop_device(setup.stdout)
        if not loop:
            raise RuntimeError(f"could not parse loop device from: {setup.stdout!r}")

        mount = subprocess.run(
            ["udisksctl", "mount", "-b", loop, "--no-user-interaction"],
            capture_output=True,
            text=True,
            check=False,
        )
        if mount.returncode != 0:
            raise RuntimeError(f"udisksctl mount: {mount.stderr.strip() or mount.stdout.strip()}")
        mp = _parse_mount_point(mount.stdout)
        if not mp:
            raise RuntimeError(f"could not parse mount point from: {mount.stdout!r}")
        return loop, Path(mp), False

    if shutil.which("fuseiso"):
        mp = Path(tempfile.mkdtemp(prefix="exwin-iso-"))
        res = subprocess.run(
            ["fuseiso", str(path), str(mp)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            mp.rmdir()  # best effort
            raise RuntimeError(f"fuseiso: {res.stderr.strip() or res.stdout.strip()}")
        return "", mp, True

    raise RuntimeError("neither udisksctl nor fuseiso found on PATH")


def _unmount_iso(state: HookState, log: Log) -> None:
    if state.iso_fuse_mounted and state.iso_mount_point:
        fusermount = shutil.which("fusermount") or shutil.which("fusermount3")
        if fusermount:
            res = subprocess.run(
                [fusermount, "-u", str(state.iso_mount_point)],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                log(f"hook: fusermount -u failed: {res.stderr.strip()}")
        try:
            state.iso_mount_point.rmdir()
        except OSError:
            pass
        return

    if state.iso_loop_device and shutil.which("udisksctl"):
        res = subprocess.run(
            ["udisksctl", "unmount", "-b", state.iso_loop_device, "--no-user-interaction"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            log(f"hook: udisksctl unmount failed: {res.stderr.strip()}")
        res = subprocess.run(
            ["udisksctl", "loop-delete", "-b", state.iso_loop_device, "--no-user-interaction"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            log(f"hook: udisksctl loop-delete failed: {res.stderr.strip()}")


def _parse_loop_device(output: str) -> str:
    m = re.search(r"/dev/loop\d+", output)
    return m.group(0) if m else ""


def _parse_mount_point(output: str) -> str:
    # udisksctl: "Mounted /dev/loop0 at /run/media/user/LABEL."
    m = re.search(r" at (\S+?)\.?\s*$", output.strip())
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Process killer
# ---------------------------------------------------------------------------


def _kill_processes(names: list[str], log: Log) -> list[str]:
    killed: list[str] = []
    pkill = shutil.which("pkill")
    if not pkill:
        log("hook: kill_processes skipped — pkill not found")
        return killed
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        if not _NAME_RE.match(name):
            log(f"hook: refusing invalid process name: {name!r}")
            continue
        res = subprocess.run(
            [pkill, "-x", name],
            capture_output=True,
            text=True,
            check=False,
        )
        # rc 0 = killed at least one; rc 1 = no matches; anything else = error.
        if res.returncode == 0:
            killed.append(name)
        elif res.returncode == 1:
            continue
        else:
            log(f"hook: pkill -x {name} rc={res.returncode} {res.stderr.strip()}")
    return killed


# ---------------------------------------------------------------------------
# KDE compositor
# ---------------------------------------------------------------------------


def _running_in_kde() -> bool:
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def _find_qdbus() -> str | None:
    for name in ("qdbus", "qdbus6", "qdbus-qt6", "qdbus-qt5"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _suspend_kde_compositor(log: Log) -> bool:
    if not _running_in_kde():
        log("hook: suspend compositor skipped — not running KDE")
        return False
    qdbus = _find_qdbus()
    if not qdbus:
        log("hook: suspend compositor skipped — qdbus not found")
        return False
    res = subprocess.run(
        [qdbus, "org.kde.KWin", "/Compositor", "suspend"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        log(f"hook: qdbus suspend failed: {res.stderr.strip() or res.stdout.strip()}")
        return False
    return True


def _resume_kde_compositor(log: Log) -> None:
    qdbus = _find_qdbus()
    if not qdbus:
        return
    res = subprocess.run(
        [qdbus, "org.kde.KWin", "/Compositor", "resume"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        log(f"hook: qdbus resume failed: {res.stderr.strip() or res.stdout.strip()}")


# ---------------------------------------------------------------------------
# CPU performance governor
# ---------------------------------------------------------------------------


def _governor_tool_available() -> str | None:
    """Which user-level governor tool can we use? Returns ``"powerprofilesctl"`` or None.

    ``pkexec cpupower`` is deliberately NOT attempted — we never prompt
    mid-launch; power-profiles-daemon is the user-level path.
    """
    if shutil.which("powerprofilesctl"):
        return "powerprofilesctl"
    return None


def _set_performance_governor(log: Log) -> str | None:
    tool = _governor_tool_available()
    if tool is None:
        log("hook: performance governor skipped — no user-level tool available")
        return None
    get = subprocess.run(
        ["powerprofilesctl", "get"],
        capture_output=True,
        text=True,
        check=False,
    )
    prior = get.stdout.strip() if get.returncode == 0 else None
    res = subprocess.run(
        ["powerprofilesctl", "set", "performance"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        log(f"hook: powerprofilesctl set performance failed: {res.stderr.strip()}")
        return None
    return prior


def _restore_governor(prior: str, log: Log) -> None:
    if not shutil.which("powerprofilesctl"):
        return
    res = subprocess.run(
        ["powerprofilesctl", "set", prior],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        log(f"hook: powerprofilesctl restore ({prior}) failed: {res.stderr.strip()}")


# ---------------------------------------------------------------------------
# Shell escape hatch
# ---------------------------------------------------------------------------


def _run_pre_shell(cmd: str, env: dict[str, str], log: Log) -> None:
    merged = {**os.environ, **env}
    res = subprocess.run(
        ["/bin/sh", "-c", cmd],
        env=merged,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.stdout:
        log(f"hook: pre_launch_cmd stdout:\n{res.stdout.rstrip()}")
    if res.stderr:
        log(f"hook: pre_launch_cmd stderr:\n{res.stderr.rstrip()}")
    if res.returncode != 0:
        out = (res.stdout or "") + (res.stderr or "")
        raise HookAbort(
            f"pre_launch_cmd exited rc={res.returncode}",
            output=out.rstrip(),
        )


def _run_post_shell(
    cmd: str,
    on_crash_only: bool,
    rc: int,
    env: dict[str, str],
    log: Log,
) -> None:
    if on_crash_only and rc == 0:
        log("hook: post_launch_cmd skipped — clean exit + on_crash_only")
        return
    merged = {**os.environ, **env}
    try:
        res = subprocess.run(
            ["/bin/sh", "-c", cmd],
            env=merged,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        log(f"hook: post_launch_cmd raised: {exc}")
        return
    if res.stdout:
        log(f"hook: post_launch_cmd stdout:\n{res.stdout.rstrip()}")
    if res.stderr:
        log(f"hook: post_launch_cmd stderr:\n{res.stderr.rstrip()}")
    if res.returncode != 0:
        log(f"hook: post_launch_cmd exited rc={res.returncode}")
