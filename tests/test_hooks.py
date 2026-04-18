"""Tests for exwin.backend.hooks (pre/post-launch curated toggles + shell)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from exwin.backend import hooks as hmod
from exwin.backend.app_config import HookConfig
from exwin.backend.hooks import (
    HookAbort,
    HookState,
    _governor_tool_available,
    _kill_processes,
    _parse_loop_device,
    _parse_mount_point,
    _running_in_kde,
    _suspend_kde_compositor,
    apply_post_hooks,
    apply_pre_hooks,
)


def _collect_log() -> tuple[list[str], callable]:
    messages: list[str] = []
    return messages, messages.append


# ---------------------------------------------------------------------------
# udisksctl output parsing
# ---------------------------------------------------------------------------


class TestParsers:
    def test_parse_loop_device(self) -> None:
        assert _parse_loop_device("Mapped file x as /dev/loop5.\n") == "/dev/loop5"
        assert _parse_loop_device("no match here") == ""

    def test_parse_mount_point(self) -> None:
        assert (
            _parse_mount_point("Mounted /dev/loop0 at /run/media/user/DISC.\n")
            == "/run/media/user/DISC"
        )
        assert _parse_mount_point("nothing to see") == ""


# ---------------------------------------------------------------------------
# Mount ISO
# ---------------------------------------------------------------------------


def _make_run(results: dict) -> callable:
    """Return a fake subprocess.run that dispatches by argv[0] + argv[1]."""

    def fake(argv, capture_output=True, text=True, check=False, env=None, **kw):
        key = tuple(argv[:2])
        if key not in results:
            raise AssertionError(f"unexpected subprocess.run argv={argv}")
        rc, out, err = results[key]
        m = MagicMock()
        m.returncode = rc
        m.stdout = out
        m.stderr = err
        return m

    return fake


class TestMountIso:
    def test_mount_iso_records_state(self, tmp_path: Path) -> None:
        iso = tmp_path / "game.iso"
        iso.write_bytes(b"fake-iso")

        # Mock udisksctl: loop-setup + mount both succeed.
        results = {
            ("udisksctl", "loop-setup"): (0, "Mapped file game.iso as /dev/loop7.\n", ""),
            ("udisksctl", "mount"): (0, "Mounted /dev/loop7 at /run/media/u/DISC.\n", ""),
        }

        env: dict[str, str] = {}
        messages, log = _collect_log()
        with (
            patch(
                "exwin.backend.hooks.shutil.which",
                side_effect=lambda n: "/usr/bin/" + n if n == "udisksctl" else None,
            ),
            patch("exwin.backend.hooks.subprocess.run", side_effect=_make_run(results)),
        ):
            state = apply_pre_hooks(HookConfig(mount_iso=str(iso)), env, log)

        assert state.iso_loop_device == "/dev/loop7"
        assert state.iso_mount_point == Path("/run/media/u/DISC")
        assert env["EXWIN_ISO_MOUNT"] == "/run/media/u/DISC"
        assert any("mounted" in m for m in messages)

    def test_missing_iso_logs_and_skips(self, tmp_path: Path) -> None:
        env: dict[str, str] = {}
        messages, log = _collect_log()
        # No subprocess.run patch — should never be called.
        with patch("exwin.backend.hooks.subprocess.run") as mock_run:
            state = apply_pre_hooks(HookConfig(mount_iso=str(tmp_path / "missing.iso")), env, log)
        mock_run.assert_not_called()
        assert state.iso_loop_device is None
        assert "EXWIN_ISO_MOUNT" not in env
        assert any("not found" in m.lower() for m in messages)

    def test_unmount_iso_reverses_on_post(self, tmp_path: Path) -> None:
        state = HookState(
            iso_loop_device="/dev/loop3",
            iso_mount_point=Path("/run/media/u/X"),
            iso_fuse_mounted=False,
        )
        results = {
            ("udisksctl", "unmount"): (0, "", ""),
            ("udisksctl", "loop-delete"): (0, "", ""),
        }
        messages, log = _collect_log()
        with (
            patch("exwin.backend.hooks.shutil.which", return_value="/usr/bin/udisksctl"),
            patch("exwin.backend.hooks.subprocess.run", side_effect=_make_run(results)) as mock_run,
        ):
            apply_post_hooks(HookConfig(), state, rc=0, env={}, log=log)
        argvs = [c.args[0] for c in mock_run.call_args_list]
        assert ["udisksctl", "unmount", "-b", "/dev/loop3", "--no-user-interaction"] in argvs
        assert ["udisksctl", "loop-delete", "-b", "/dev/loop3", "--no-user-interaction"] in argvs

    def test_mount_failure_logs_and_continues(self, tmp_path: Path) -> None:
        iso = tmp_path / "broken.iso"
        iso.write_bytes(b"x")
        results = {("udisksctl", "loop-setup"): (1, "", "permission denied\n")}
        env: dict[str, str] = {}
        messages, log = _collect_log()
        with (
            patch(
                "exwin.backend.hooks.shutil.which",
                side_effect=lambda n: "/usr/bin/" + n if n == "udisksctl" else None,
            ),
            patch("exwin.backend.hooks.subprocess.run", side_effect=_make_run(results)),
        ):
            state = apply_pre_hooks(HookConfig(mount_iso=str(iso)), env, log)
        assert state.iso_loop_device is None
        assert "EXWIN_ISO_MOUNT" not in env
        assert any("mount ISO failed" in m for m in messages)


# ---------------------------------------------------------------------------
# Kill processes
# ---------------------------------------------------------------------------


class TestKillProcesses:
    def test_kill_processes_validates_names(self) -> None:
        messages, log = _collect_log()
        calls: list[list[str]] = []

        def fake_run(argv, capture_output=True, text=True, check=False, **kw):
            calls.append(argv)
            m = MagicMock()
            m.returncode = 0
            m.stdout = m.stderr = ""
            return m

        with (
            patch("exwin.backend.hooks.shutil.which", return_value="/usr/bin/pkill"),
            patch("exwin.backend.hooks.subprocess.run", side_effect=fake_run),
        ):
            killed = _kill_processes(["good", "bad;name", "also$bad", "ok.proc"], log)

        # Shell-metachar names refused; good names ran.
        argv_bins = [c[2] for c in calls]
        assert "good" in argv_bins
        assert "ok.proc" in argv_bins
        assert "bad;name" not in argv_bins
        assert "also$bad" not in argv_bins
        assert killed == ["good", "ok.proc"]
        assert any("refusing invalid" in m for m in messages)

    def test_kill_returns_rc1_no_matches(self) -> None:
        messages, log = _collect_log()

        def fake_run(argv, **kw):
            m = MagicMock()
            m.returncode = 1  # pkill: no matches
            m.stdout = m.stderr = ""
            return m

        with (
            patch("exwin.backend.hooks.shutil.which", return_value="/usr/bin/pkill"),
            patch("exwin.backend.hooks.subprocess.run", side_effect=fake_run),
        ):
            killed = _kill_processes(["nonexistent"], log)
        assert killed == []
        # No-match is not an error — no log entry for it
        assert not any("rc=" in m for m in messages)

    def test_no_pkill_skips(self) -> None:
        messages, log = _collect_log()
        with patch("exwin.backend.hooks.shutil.which", return_value=None):
            killed = _kill_processes(["foo"], log)
        assert killed == []
        assert any("pkill not found" in m for m in messages)


# ---------------------------------------------------------------------------
# KDE compositor
# ---------------------------------------------------------------------------


class TestKDECompositor:
    def test_gated_by_desktop(self) -> None:
        messages, log = _collect_log()
        with patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"}, clear=False):
            got = _suspend_kde_compositor(log)
        assert got is False
        assert any("not running KDE" in m for m in messages)

    def test_records_prior_state_when_suspended(self) -> None:
        messages, log = _collect_log()

        def fake_run(argv, **kw):
            m = MagicMock()
            m.returncode = 0
            m.stdout = m.stderr = ""
            return m

        with (
            patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "KDE"}, clear=False),
            patch(
                "exwin.backend.hooks.shutil.which",
                side_effect=lambda n: "/usr/bin/qdbus" if n == "qdbus" else None,
            ),
            patch("exwin.backend.hooks.subprocess.run", side_effect=fake_run) as mock_run,
        ):
            got = _suspend_kde_compositor(log)
        assert got is True
        argv = mock_run.call_args_list[0].args[0]
        assert argv[1:] == ["org.kde.KWin", "/Compositor", "suspend"]

    def test_running_in_kde_detects_plasma_variants(self) -> None:
        with patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "KDE"}, clear=False):
            assert _running_in_kde() is True
        with patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"}, clear=False):
            assert _running_in_kde() is False


# ---------------------------------------------------------------------------
# Governor
# ---------------------------------------------------------------------------


class TestGovernor:
    def test_prefers_powerprofilesctl(self) -> None:
        with patch(
            "exwin.backend.hooks.shutil.which",
            side_effect=lambda n: (
                "/usr/bin/" + n if n in ("powerprofilesctl", "cpupower", "pkexec") else None
            ),
        ):
            assert _governor_tool_available() == "powerprofilesctl"

    def test_gracefully_disabled_when_no_tool(self) -> None:
        messages, log = _collect_log()
        with patch("exwin.backend.hooks.shutil.which", return_value=None):
            prior = hmod._set_performance_governor(log)
        assert prior is None
        assert any("no user-level tool" in m for m in messages)

    def test_sets_performance_and_returns_prior(self) -> None:
        results = {
            ("powerprofilesctl", "get"): (0, "balanced\n", ""),
            ("powerprofilesctl", "set"): (0, "", ""),
        }
        messages, log = _collect_log()
        with (
            patch("exwin.backend.hooks.shutil.which", return_value="/usr/bin/powerprofilesctl"),
            patch("exwin.backend.hooks.subprocess.run", side_effect=_make_run(results)),
        ):
            prior = hmod._set_performance_governor(log)
        assert prior == "balanced"

    def test_restore_governor_roundtrips(self) -> None:
        state = HookState(prior_power_profile="balanced")
        calls: list[list[str]] = []

        def fake_run(argv, **kw):
            calls.append(argv)
            m = MagicMock()
            m.returncode = 0
            m.stdout = m.stderr = ""
            return m

        messages, log = _collect_log()
        with (
            patch("exwin.backend.hooks.shutil.which", return_value="/usr/bin/powerprofilesctl"),
            patch("exwin.backend.hooks.subprocess.run", side_effect=fake_run),
        ):
            apply_post_hooks(HookConfig(), state, rc=0, env={}, log=log)
        assert ["powerprofilesctl", "set", "balanced"] in calls


# ---------------------------------------------------------------------------
# Shell escape hatch
# ---------------------------------------------------------------------------


class TestShellHatch:
    def test_pre_launch_cmd_failure_raises_hook_abort(self) -> None:
        messages, log = _collect_log()
        with pytest.raises(HookAbort) as exc:
            apply_pre_hooks(
                HookConfig(pre_launch_cmd="echo boom; exit 9"),
                env={},
                log=log,
            )
        assert exc.value.reason.startswith("pre_launch_cmd exited rc=9")

    def test_pre_launch_cmd_success_records_nothing(self) -> None:
        messages, log = _collect_log()
        state = apply_pre_hooks(
            HookConfig(pre_launch_cmd="true"),
            env={},
            log=log,
        )
        assert state == HookState()

    def test_post_launch_on_crash_only_skips_rc0(self) -> None:
        messages, log = _collect_log()
        with patch("exwin.backend.hooks.subprocess.run") as mock_run:
            apply_post_hooks(
                HookConfig(post_launch_cmd="echo ran", post_launch_on_crash_only=True),
                HookState(),
                rc=0,
                env={},
                log=log,
            )
        mock_run.assert_not_called()
        assert any("on_crash_only" in m for m in messages)

    def test_post_launch_on_crash_only_runs_on_nonzero(self) -> None:
        messages, log = _collect_log()
        with patch("exwin.backend.hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            apply_post_hooks(
                HookConfig(post_launch_cmd="echo ran", post_launch_on_crash_only=True),
                HookState(),
                rc=1,
                env={},
                log=log,
            )
        mock_run.assert_called_once()
        argv = mock_run.call_args.args[0]
        assert argv[:2] == ["/bin/sh", "-c"]
        assert argv[2] == "echo ran"

    def test_post_launch_failure_logged_not_raised(self) -> None:
        messages, log = _collect_log()
        with patch("exwin.backend.hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=7, stdout="", stderr="")
            # Should not raise
            apply_post_hooks(
                HookConfig(post_launch_cmd="false"),
                HookState(),
                rc=0,
                env={},
                log=log,
            )
        assert any("rc=7" in m for m in messages)

    def test_env_is_forwarded_to_shell(self) -> None:
        """$EXWIN_ISO_MOUNT should be visible to the pre/post shell."""
        messages, log = _collect_log()
        with patch("exwin.backend.hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            apply_pre_hooks(
                HookConfig(pre_launch_cmd="true"),
                env={"EXWIN_ISO_MOUNT": "/mnt/disc"},
                log=log,
            )
        env_passed = mock_run.call_args.kwargs["env"]
        assert env_passed["EXWIN_ISO_MOUNT"] == "/mnt/disc"


# ---------------------------------------------------------------------------
# apply_pre_hooks / apply_post_hooks ordering and best-effort semantics
# ---------------------------------------------------------------------------


class TestToggleOrderingAndResilience:
    def test_toggle_failure_does_not_stop_others(self, tmp_path: Path) -> None:
        """If mount_iso fails, kill_processes should still be attempted."""
        iso = tmp_path / "bad.iso"
        iso.write_bytes(b"x")

        calls: list[list[str]] = []

        def fake_run(argv, **kw):
            calls.append(argv)
            m = MagicMock()
            m.returncode = 1 if argv[:2] == ["udisksctl", "loop-setup"] else 0
            m.stdout = m.stderr = ""
            return m

        messages, log = _collect_log()
        with (
            patch(
                "exwin.backend.hooks.shutil.which",
                side_effect=lambda n: "/usr/bin/" + n if n in ("udisksctl", "pkill") else None,
            ),
            patch("exwin.backend.hooks.subprocess.run", side_effect=fake_run),
        ):
            state = apply_pre_hooks(
                HookConfig(mount_iso=str(iso), kill_processes=["foo"]),
                env={},
                log=log,
            )
        # ISO failed → state not populated; pkill still ran
        assert state.iso_loop_device is None
        assert any(c[:2] == ["/usr/bin/pkill", "-x"] for c in calls)
