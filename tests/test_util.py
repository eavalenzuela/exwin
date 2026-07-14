"""Tests for exwin.util helpers."""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import patch

from exwin.backend.archive_installer import _find_rar_tool
from exwin.backend.gog_installer import find_rar_tool
from exwin.util import tool_usable


def _script(path: Path, body: str) -> str:
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


class TestToolUsable:
    def test_missing_binary(self, tmp_path: Path) -> None:
        assert tool_usable(str(tmp_path / "nope")) is False

    def test_working_binary(self, tmp_path: Path) -> None:
        assert tool_usable(_script(tmp_path / "ok", "exit 0")) is True

    def test_nonzero_but_running_binary(self, tmp_path: Path) -> None:
        # Tools that reject --version still count as usable.
        assert tool_usable(_script(tmp_path / "grumpy", "exit 1")) is True

    def test_loader_failure_exit_127(self, tmp_path: Path) -> None:
        # A host binary seen through a sandbox exits 127 without running
        # (dynamic loader failure / wrapper script with missing target).
        assert tool_usable(_script(tmp_path / "broken", "exit 127")) is False

    def test_not_executable(self, tmp_path: Path) -> None:
        f = tmp_path / "plain"
        f.write_text("data")
        assert tool_usable(str(f)) is False


class TestRarToolFiltering:
    def test_archive_installer_skips_unusable_candidate(self) -> None:
        paths = {"unar": "/fake/unar", "unrar": "/fake/unrar"}
        with (
            patch("exwin.backend.archive_installer.shutil.which", side_effect=paths.get),
            patch(
                "exwin.backend.archive_installer.tool_usable",
                side_effect=lambda p: p == "/fake/unrar",
            ),
        ):
            assert _find_rar_tool() == "/fake/unrar"

    def test_archive_installer_none_when_all_broken(self) -> None:
        with (
            patch("exwin.backend.archive_installer.shutil.which", return_value="/fake/tool"),
            patch("exwin.backend.archive_installer.tool_usable", return_value=False),
        ):
            assert _find_rar_tool() is None

    def test_gog_installer_skips_unusable_candidate(self) -> None:
        paths = {"unrar": "/fake/unrar", "unar": "/fake/unar"}
        with (
            patch("exwin.backend.gog_installer.shutil.which", side_effect=paths.get),
            patch(
                "exwin.backend.gog_installer.tool_usable",
                side_effect=lambda p: p == "/fake/unar",
            ),
        ):
            assert find_rar_tool() == "/fake/unar"
