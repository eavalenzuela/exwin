"""Resolve Steam app IDs from game names via Steam's public search API."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

_log = logging.getLogger(__name__)

_SEARCH_URL = "https://store.steampowered.com/api/storesearch/?term={term}&cc=us&l=en"
_TIMEOUT = 10  # seconds

# Manual overrides for names that resolve poorly (e.g. GOG edition vs Steam title).
# Extend as real mismatches surface.
_ALIASES: dict[str, int] = {}


def resolve_steam_appid(name: str) -> int | None:
    """Return the first Steam app ID matching *name*, or None if no match or error."""
    cleaned = _clean_name(name)
    if not cleaned:
        return None
    if cleaned in _ALIASES:
        return _ALIASES[cleaned]

    url = _SEARCH_URL.format(term=urllib.parse.quote(cleaned))
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        _log.exception("Steam app ID search failed for %r", name)
        return None

    items = data.get("items", []) if isinstance(data, dict) else []
    if not items:
        return None
    appid = items[0].get("id")
    return int(appid) if isinstance(appid, int) else None


_SUFFIXES = (
    " - GOG",
    ": Complete Edition",
    " - Complete Edition",
    ": Enhanced Edition",
    " Enhanced Edition",
    " - Definitive Edition",
    " Definitive Edition",
    " - Remastered",
    " Remastered",
    " GOTY Edition",
)


def _clean_name(name: str) -> str:
    """Strip GOG/edition suffixes that tend to miss on the Steam search endpoint."""
    cleaned = name.strip()
    # Keep stripping recognised suffixes until nothing changes.
    changed = True
    while changed:
        changed = False
        for suffix in _SUFFIXES:
            if cleaned.lower().endswith(suffix.lower()):
                cleaned = cleaned[: -len(suffix)].strip()
                changed = True
    return cleaned
