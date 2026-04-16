"""Tests for exwin.backend.steam_appid — Steam app ID resolution."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

from exwin.backend.steam_appid import _clean_name, resolve_steam_appid


def _make_response(payload: dict):
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


class TestResolve:
    def test_returns_first_match_id(self) -> None:
        payload = {"items": [{"id": 620, "name": "Portal 2"}, {"id": 400, "name": "Portal"}]}
        with patch(
            "exwin.backend.steam_appid.urllib.request.urlopen",
            return_value=_make_response(payload),
        ):
            assert resolve_steam_appid("Portal 2") == 620

    def test_empty_items_returns_none(self) -> None:
        with patch(
            "exwin.backend.steam_appid.urllib.request.urlopen",
            return_value=_make_response({"items": []}),
        ):
            assert resolve_steam_appid("Obscure Game XYZ") is None

    def test_network_error_returns_none(self) -> None:
        with patch(
            "exwin.backend.steam_appid.urllib.request.urlopen",
            side_effect=OSError("no net"),
        ):
            assert resolve_steam_appid("Portal 2") is None

    def test_non_int_id_returns_none(self) -> None:
        with patch(
            "exwin.backend.steam_appid.urllib.request.urlopen",
            return_value=_make_response({"items": [{"id": "bogus", "name": "x"}]}),
        ):
            assert resolve_steam_appid("Whatever") is None

    def test_empty_name_returns_none(self) -> None:
        assert resolve_steam_appid("") is None
        assert resolve_steam_appid("   ") is None


class TestCleanName:
    def test_strip_gog_suffix(self) -> None:
        assert _clean_name("Hidden & Dangerous 2 - GOG") == "Hidden & Dangerous 2"

    def test_strip_remastered(self) -> None:
        assert _clean_name("Quake Remastered") == "Quake"

    def test_strip_chained_suffixes(self) -> None:
        assert (
            _clean_name("The Witcher 3: Wild Hunt - Complete Edition - GOG")
            == "The Witcher 3: Wild Hunt"
        )

    def test_case_insensitive(self) -> None:
        assert _clean_name("Balrum - gog") == "Balrum"

    def test_no_suffix_unchanged(self) -> None:
        assert _clean_name("Balrum") == "Balrum"
