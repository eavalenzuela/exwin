"""Tests for exwin.backend.protondb — parsing and cache behavior."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from exwin.backend.protondb import (
    CACHE_TTL,
    ProtonTweaks,
    extract_tweaks,
    fetch_summary,
    fetch_top_reports,
)

# ---------------------------------------------------------------------------
# extract_tweaks
# ---------------------------------------------------------------------------


class TestExtractTweaks:
    def test_empty_reports(self) -> None:
        assert extract_tweaks([]).is_empty()

    def test_picks_up_known_env_vars(self) -> None:
        reports = [{"notes": "Set PROTON_NO_ESYNC=1 and it works."}]
        tweaks = extract_tweaks(reports)
        assert tweaks.env == {"PROTON_NO_ESYNC": "1"}

    def test_ignores_unknown_all_caps_env(self) -> None:
        # SOME_RANDOM_VAR is not in the allowlist — must not land in env.
        reports = [{"notes": "Fixed by setting SOME_RANDOM_VAR=foo in launch options"}]
        assert extract_tweaks(reports).env == {}

    def test_multiple_env_vars(self) -> None:
        reports = [{"notes": "PROTON_NO_ESYNC=1 PROTON_NO_FSYNC=1 WINEDEBUG=-all %command%"}]
        env = extract_tweaks(reports).env
        assert env["PROTON_NO_ESYNC"] == "1"
        assert env["PROTON_NO_FSYNC"] == "1"
        assert env["WINEDEBUG"] == "-all"

    def test_launch_args_before_command(self) -> None:
        reports = [{"notes": "Run with -dx11 -windowed %command% and it launches"}]
        tweaks = extract_tweaks(reports)
        assert "-dx11" in tweaks.launch_args
        assert "-windowed" in tweaks.launch_args

    def test_winetricks_verb_line(self) -> None:
        reports = [{"notes": "Ran winetricks vcrun2019 dotnet48 to fix crash"}]
        verbs = extract_tweaks(reports).verbs
        assert "vcrun2019" in verbs
        assert "dotnet48" in verbs

    def test_winetricks_with_flag(self) -> None:
        reports = [{"notes": "winetricks --force vcrun2015 dxvk helped"}]
        verbs = extract_tweaks(reports).verbs
        assert "vcrun2015" in verbs
        assert "dxvk" in verbs

    def test_dll_overrides_parsed(self) -> None:
        reports = [{"notes": 'Launch with WINEDLLOVERRIDES="dinput8=n;d3d11=b" %command%'}]
        tweaks = extract_tweaks(reports)
        assert tweaks.dll_overrides == {"dinput8": "n", "d3d11": "b"}
        # When WINEDLLOVERRIDES produces overrides, it should not double-up in env.
        assert "WINEDLLOVERRIDES" not in tweaks.env

    def test_dedupe_across_reports(self) -> None:
        reports = [
            {"notes": "-dx11 %command%"},
            {"notes": "-dx11 -windowed %command%"},
            {"notes": "winetricks vcrun2019"},
            {"notes": "winetricks vcrun2019"},
        ]
        tweaks = extract_tweaks(reports)
        assert tweaks.launch_args.count("-dx11") == 1
        assert tweaks.verbs.count("vcrun2019") == 1

    def test_report_bodies_alternate_keys(self) -> None:
        # Report schema has varied historically — try several body keys.
        reports = [
            {"body": "PROTON_NO_ESYNC=1 %command%"},
            {"comment": "winetricks dxvk"},
            {"text": "-nosplash %command%"},
        ]
        tweaks = extract_tweaks(reports)
        assert tweaks.env == {"PROTON_NO_ESYNC": "1"}
        assert "dxvk" in tweaks.verbs
        assert "-nosplash" in tweaks.launch_args


# ---------------------------------------------------------------------------
# fetch_summary / fetch_top_reports with mocked urlopen + cache
# ---------------------------------------------------------------------------


def _make_response(payload: dict | list):
    """Return a context manager mimicking urlopen()'s response object."""

    class _Resp:
        def __init__(self) -> None:
            self._buf = BytesIO(json.dumps(payload).encode("utf-8"))

        def read(self, *a, **kw) -> bytes:
            return self._buf.read(*a, **kw)

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a) -> None:
            return None

    return _Resp()


class TestFetchSummary:
    def test_returns_parsed_json(self, tmp_path: Path) -> None:
        payload = {"tier": "gold", "total": 150, "confidence": "strong", "score": 0.82}
        with patch(
            "exwin.backend.protondb.urllib.request.urlopen", return_value=_make_response(payload)
        ):
            out = fetch_summary(620, cache_dir=tmp_path)
        assert out == payload

    def test_writes_cache_on_success(self, tmp_path: Path) -> None:
        payload = {"tier": "platinum", "total": 42}
        with patch(
            "exwin.backend.protondb.urllib.request.urlopen", return_value=_make_response(payload)
        ):
            fetch_summary(400, cache_dir=tmp_path)
        assert (tmp_path / "400_summary.json").exists()

    def test_cache_hit_skips_network(self, tmp_path: Path) -> None:
        cached = {"tier": "silver", "total": 10}
        (tmp_path / "400_summary.json").write_text(json.dumps(cached))
        with patch("exwin.backend.protondb.urllib.request.urlopen") as mocked:
            out = fetch_summary(400, cache_dir=tmp_path)
        assert out == cached
        mocked.assert_not_called()

    def test_cache_miss_after_ttl(self, tmp_path: Path) -> None:
        cached_path = tmp_path / "400_summary.json"
        cached_path.write_text(json.dumps({"tier": "stale"}))
        # Backdate mtime past TTL.
        stale = time.time() - (CACHE_TTL + timedelta(hours=1)).total_seconds()
        import os

        os.utime(cached_path, (stale, stale))

        fresh = {"tier": "gold", "total": 99}
        with patch(
            "exwin.backend.protondb.urllib.request.urlopen", return_value=_make_response(fresh)
        ) as mocked:
            out = fetch_summary(400, cache_dir=tmp_path)
        assert out == fresh
        assert mocked.call_count == 1

    def test_returns_none_on_network_error(self, tmp_path: Path) -> None:
        with patch("exwin.backend.protondb.urllib.request.urlopen", side_effect=OSError("no net")):
            assert fetch_summary(620, cache_dir=tmp_path) is None
        assert not list(tmp_path.iterdir())  # nothing cached on failure

    def test_returns_none_on_non_dict_payload(self, tmp_path: Path) -> None:
        with patch(
            "exwin.backend.protondb.urllib.request.urlopen", return_value=_make_response([1, 2])
        ):
            assert fetch_summary(620, cache_dir=tmp_path) is None


class TestFetchTopReports:
    def test_list_payload(self, tmp_path: Path) -> None:
        payload = [{"notes": "works"}, {"notes": "crashes"}]
        with patch(
            "exwin.backend.protondb.urllib.request.urlopen", return_value=_make_response(payload)
        ):
            out = fetch_top_reports(620, cache_dir=tmp_path)
        assert out == payload

    def test_wrapped_dict_payload(self, tmp_path: Path) -> None:
        payload = {"reports": [{"notes": "works"}]}
        with patch(
            "exwin.backend.protondb.urllib.request.urlopen", return_value=_make_response(payload)
        ):
            out = fetch_top_reports(620, cache_dir=tmp_path)
        assert out == [{"notes": "works"}]

    def test_error_returns_empty(self, tmp_path: Path) -> None:
        with patch("exwin.backend.protondb.urllib.request.urlopen", side_effect=OSError("boom")):
            assert fetch_top_reports(620, cache_dir=tmp_path) == []


# ---------------------------------------------------------------------------
# ProtonTweaks helpers
# ---------------------------------------------------------------------------


class TestProtonTweaks:
    def test_is_empty_defaults(self) -> None:
        assert ProtonTweaks().is_empty()

    def test_is_empty_false_when_any_field_set(self) -> None:
        assert not ProtonTweaks(verbs=["dxvk"]).is_empty()
        assert not ProtonTweaks(launch_args=["-dx11"]).is_empty()
        assert not ProtonTweaks(env={"A": "1"}).is_empty()
        assert not ProtonTweaks(dll_overrides={"d3d11": "n"}).is_empty()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
