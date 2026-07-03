"""Shared fixtures for the exwin test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from exwin.backend.config import Config
from exwin.db.schema import init_db


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    """A Config rooted in a temporary directory with all subdirs created.

    ``inhibit_idle`` is disabled so command-building tests are deterministic
    regardless of whether the host has systemd-inhibit installed; tests that
    exercise the inhibitor enable it explicitly.
    """
    cfg = Config(data_dir=tmp_path / "exwin", inhibit_idle=False)
    cfg._ensure_dirs()
    return cfg


@pytest.fixture
def db(tmp_config: Config) -> Config:
    """Initialised SQLite DB; returns the Config so callers can reach data_dir."""
    init_db(tmp_config.data_dir)
    return tmp_config


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "ui: tests that require a live GTK display (run with xvfb-run or a real $DISPLAY)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip @pytest.mark.ui tests when no display is available."""
    if os.environ.get("DISPLAY"):
        return
    skip_no_display = pytest.mark.skip(reason="No DISPLAY — run with xvfb-run or set $DISPLAY")
    for item in items:
        if item.get_closest_marker("ui"):
            item.add_marker(skip_no_display)
