"""Tests for exwin.backend.winetricks_catalog."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from exwin.backend import winetricks_catalog as wc
from exwin.backend.winetricks_catalog import (
    Verb,
    load_catalog,
    parse_list_all,
)


class TestParseListAll:
    def test_parses_categories_and_verbs(self) -> None:
        text = (
            "===== fonts =====\n"
            "corefonts  MS core fonts\n"
            "cjkfonts  Japanese/Chinese/Korean fonts\n"
            "===== dlls =====\n"
            "vcrun2019  Visual C++ 2015-2019 runtime\n"
        )
        verbs = parse_list_all(text)
        assert [(v.name, v.category) for v in verbs] == [
            ("corefonts", "fonts"),
            ("cjkfonts", "fonts"),
            ("vcrun2019", "dlls"),
        ]

    def test_ignores_lines_without_double_space(self) -> None:
        text = "===== dlls =====\nnope single-space line\nvcrun2019  desc\n"
        verbs = parse_list_all(text)
        assert [v.name for v in verbs] == ["vcrun2019"]

    def test_defaults_to_misc_when_no_header(self) -> None:
        verbs = parse_list_all("alpha  first\nbeta  second\n")
        assert all(v.category == "misc" for v in verbs)


class TestLoadCatalog:
    def test_uses_cache_when_present(self, tmp_path: Path) -> None:
        cache = tmp_path / "verbs.json"
        cache.write_text(json.dumps([{"name": "x", "category": "dlls", "description": "d"}]))
        with patch.object(wc, "CACHE_FILE", cache):
            verbs = load_catalog()
        assert verbs == [Verb(name="x", category="dlls", description="d")]

    def test_falls_back_when_probe_returns_nothing(self, tmp_path: Path) -> None:
        cache = tmp_path / "verbs.json"  # does not exist
        with (
            patch.object(wc, "CACHE_FILE", cache),
            patch.object(wc, "_probe_winetricks", return_value=[]),
        ):
            verbs = load_catalog()
        # Fallback list is bundled and non-empty.
        assert verbs
        assert any(v.name == "corefonts" for v in verbs)

    def test_writes_cache_on_successful_probe(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache" / "verbs.json"
        probed = [Verb(name="vcrun2019", category="dlls", description="VC++")]
        with (
            patch.object(wc, "CACHE_FILE", cache),
            patch.object(wc, "_probe_winetricks", return_value=probed),
        ):
            load_catalog(force_refresh=True)
        assert cache.exists()
        data = json.loads(cache.read_text())
        assert data[0]["name"] == "vcrun2019"

    def test_ignores_corrupt_cache(self, tmp_path: Path) -> None:
        cache = tmp_path / "verbs.json"
        cache.write_text("{not valid json")
        probed = [Verb(name="xact", category="dlls", description="XAudio")]
        with (
            patch.object(wc, "CACHE_FILE", cache),
            patch.object(wc, "_probe_winetricks", return_value=probed),
        ):
            verbs = load_catalog()
        assert verbs == probed
