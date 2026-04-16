"""ProtonDB API client: fetch tier summary, reports, and mine tweaks from reports.

Cache responses to ``~/.exwin/cache/protondb/`` with a 7-day TTL so repeated
dialog opens don't hammer the API. Entirely opt-in: nothing here is called
until the user clicks the "Check ProtonDB" button.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

_log = logging.getLogger(__name__)

CACHE_TTL = timedelta(days=7)
_TIMEOUT = 10

_SUMMARY_URL = "https://www.protondb.com/api/v1/reports/summaries/{appid}.json"
_REPORTS_URL = "https://www.protondb.com/api/v1/reports/app/{appid}.json"


@dataclass
class ProtonTweaks:
    launch_args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    verbs: list[str] = field(default_factory=list)
    dll_overrides: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.launch_args or self.env or self.verbs or self.dll_overrides)


# Only these env var keys are promoted out of report bodies; everything else is
# ignored to avoid false positives from stray ALL_CAPS tokens.
_KNOWN_ENV: frozenset[str] = frozenset(
    {
        "PROTON_NO_ESYNC",
        "PROTON_NO_FSYNC",
        "PROTON_USE_WINED3D",
        "PROTON_FORCE_LARGE_ADDRESS_AWARE",
        "PROTON_HIDE_NVIDIA_GPU",
        "PROTON_ENABLE_NVAPI",
        "PROTON_ENABLE_WAYLAND",
        "PROTON_LOG",
        "DXVK_ASYNC",
        "DXVK_HUD",
        "DXVK_FRAME_RATE",
        "WINEESYNC",
        "WINEFSYNC",
        "WINEDEBUG",
        "WINEDLLOVERRIDES",
        "MANGOHUD",
        "VKD3D_CONFIG",
        "__GL_THREADED_OPTIMIZATIONS",
        "__NV_PRIME_RENDER_OFFLOAD",
    }
)

_ENV_RE = re.compile(r"([A-Z_][A-Z0-9_]{2,})=([^\s%]+)")
_VERB_LINE_RE = re.compile(r"winetricks(?:\s+-[-\w]+)*\s+([\w\-\s.]+)", re.IGNORECASE)
_LAUNCH_ARGS_RE = re.compile(r"((?:-\S+\s+)*-\S+)\s*%command%")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_summary(appid: int, cache_dir: Path | None = None) -> dict | None:
    """Return ProtonDB summary JSON (tier/confidence/score/total) or None on error."""
    cached_path = _cache_path(cache_dir, appid, "summary") if cache_dir else None
    if cached_path is not None:
        cached = _read_cached(cached_path, CACHE_TTL)
        if isinstance(cached, dict):
            return cached
    data = _fetch_json(_SUMMARY_URL.format(appid=appid))
    if not isinstance(data, dict):
        return None
    if cached_path is not None:
        _write_cache(cached_path, data)
    return data


def fetch_top_reports(appid: int, cache_dir: Path | None = None) -> list[dict]:
    """Return a list of recent ProtonDB reports; empty list on error."""
    cached_path = _cache_path(cache_dir, appid, "reports") if cache_dir else None
    if cached_path is not None:
        cached = _read_cached(cached_path, CACHE_TTL)
        if isinstance(cached, list):
            return cached
    data = _fetch_json(_REPORTS_URL.format(appid=appid))
    reports: list[dict] = []
    if isinstance(data, list):
        reports = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        raw = data.get("reports", [])
        if isinstance(raw, list):
            reports = [r for r in raw if isinstance(r, dict)]
    if cached_path is not None and reports:
        _write_cache(cached_path, reports)
    return reports


def extract_tweaks(reports: list[dict]) -> ProtonTweaks:
    """Mine report bodies for launch args, env vars, winetricks verbs, DLL overrides."""
    tweaks = ProtonTweaks()
    for report in reports:
        body = _report_body(report)
        if not body:
            continue
        _extract_env_and_dll(body, tweaks)
        _extract_verbs(body, tweaks)
        _extract_launch_args(body, tweaks)
    return tweaks


# ---------------------------------------------------------------------------
# Internals — report parsing
# ---------------------------------------------------------------------------


def _report_body(report: dict) -> str:
    for key in ("notes", "body", "comment", "text"):
        val = report.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


def _extract_env_and_dll(body: str, tweaks: ProtonTweaks) -> None:
    for match in _ENV_RE.finditer(body):
        key, val = match.group(1), match.group(2)
        if key not in _KNOWN_ENV:
            continue
        val = val.strip("\"'")
        if key == "WINEDLLOVERRIDES":
            for dll, mode in _parse_dll_overrides(val):
                tweaks.dll_overrides.setdefault(dll, mode)
            continue
        tweaks.env.setdefault(key, val)


def _extract_verbs(body: str, tweaks: ProtonTweaks) -> None:
    for match in _VERB_LINE_RE.finditer(body):
        for token in match.group(1).split():
            verb = token.strip().strip(".,").lower()
            # Verbs are short alnum tokens; skip anything that doesn't look like one.
            if verb and re.fullmatch(r"[a-z0-9_]+", verb) and verb not in tweaks.verbs:
                tweaks.verbs.append(verb)


def _extract_launch_args(body: str, tweaks: ProtonTweaks) -> None:
    for match in _LAUNCH_ARGS_RE.finditer(body):
        for token in match.group(1).split():
            if token.startswith("-") and token not in tweaks.launch_args:
                tweaks.launch_args.append(token)


def _parse_dll_overrides(raw: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for chunk in raw.split(";"):
        if "=" not in chunk:
            continue
        dll, mode = chunk.split("=", 1)
        dll, mode = dll.strip(), mode.strip()
        if dll and mode:
            out.append((dll, mode))
    return out


# ---------------------------------------------------------------------------
# Internals — fetch + cache
# ---------------------------------------------------------------------------


def _fetch_json(url: str) -> dict | list | None:
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        _log.exception("ProtonDB fetch failed: %s", url)
        return None


def _cache_path(cache_dir: Path, appid: int, kind: str) -> Path:
    return cache_dir / f"{appid}_{kind}.json"


def _read_cached(path: Path, ttl: timedelta) -> dict | list | None:
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl.total_seconds():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    tmp.replace(path)
