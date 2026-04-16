"""Winetricks verb catalog — parses ``winetricks --list-all`` output with caching.

The catalog feeds the picker UI.  First call shells out to ``winetricks
--list-all`` (~300ms) and caches the result in ``~/.exwin/cache``.  When
winetricks is unavailable or the probe fails we fall back to a small
hand-curated list of common verbs so the picker still renders.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

CACHE_FILE = Path.home() / ".exwin" / "cache" / "winetricks_verbs.json"

# Minimal fallback for when `winetricks --list-all` can't run.
_FALLBACK: list[dict] = [
    {
        "name": "corefonts",
        "category": "fonts",
        "description": "MS Arial, Courier New, Times New Roman, Tahoma, Verdana, Webdings",
    },
    {
        "name": "cjkfonts",
        "category": "fonts",
        "description": "Japanese/Chinese/Korean fonts",
    },
    {
        "name": "vcrun2019",
        "category": "dlls",
        "description": "Visual C++ 2015-2019 runtime",
    },
    {
        "name": "vcrun2015",
        "category": "dlls",
        "description": "Visual C++ 2015 runtime",
    },
    {
        "name": "vcrun2013",
        "category": "dlls",
        "description": "Visual C++ 2013 runtime",
    },
    {
        "name": "vcrun2010",
        "category": "dlls",
        "description": "Visual C++ 2010 runtime",
    },
    {
        "name": "d3dx9",
        "category": "dlls",
        "description": "MS D3DX9_xx.dll (DirectX 9 shader helpers)",
    },
    {
        "name": "d3dx11_43",
        "category": "dlls",
        "description": "MS D3DX11_43.dll",
    },
    {
        "name": "d3dcompiler_47",
        "category": "dlls",
        "description": "MS d3dcompiler_47.dll",
    },
    {
        "name": "xact",
        "category": "dlls",
        "description": "XACT audio engine",
    },
    {
        "name": "mf-install",
        "category": "dlls",
        "description": "Media Foundation (video playback in many modern games)",
    },
    {
        "name": "dotnet48",
        "category": "dlls",
        "description": "MS .NET 4.8",
    },
    {
        "name": "dotnet40",
        "category": "dlls",
        "description": "MS .NET 4.0",
    },
    {
        "name": "dotnet35",
        "category": "dlls",
        "description": "MS .NET 3.5",
    },
    {
        "name": "directplay",
        "category": "dlls",
        "description": "DirectPlay (older multiplayer)",
    },
    {
        "name": "faudio",
        "category": "dlls",
        "description": "FAudio (XAudio2 replacement)",
    },
    {
        "name": "physx",
        "category": "dlls",
        "description": "NVIDIA PhysX runtime",
    },
    {
        "name": "quartz",
        "category": "dlls",
        "description": "DirectShow quartz.dll",
    },
    {
        "name": "dxvk",
        "category": "dlls",
        "description": "Vulkan-based DirectX 9/10/11 implementation",
    },
]

# Curated preset bundles — surfaced as quick-apply buttons in the picker.
PRESETS: dict[str, list[str]] = {
    "DirectX 9 base": ["d3dx9", "vcrun2013", "corefonts"],
    "Modern DX11 + .NET": ["vcrun2019", "d3dcompiler_47", "dotnet48"],
    "FAudio + Media Foundation": ["faudio", "mf-install"],
}

# Verbs the picker highlights in a "Popular" group at the top.
POPULAR_NAMES = frozenset(
    {
        "corefonts",
        "cjkfonts",
        "vcrun2019",
        "vcrun2015",
        "d3dx9",
        "d3dcompiler_47",
        "mf-install",
        "dotnet48",
        "xact",
        "faudio",
        "dxvk",
    }
)


@dataclass(frozen=True)
class Verb:
    name: str
    category: str
    description: str


def is_available() -> bool:
    return shutil.which("winetricks") is not None


def load_catalog(force_refresh: bool = False) -> list[Verb]:
    """Return the full verb catalog.

    Uses the on-disk cache when available; otherwise shells out to
    ``winetricks --list-all``.  If neither path yields verbs, falls back to
    the bundled minimal list so the picker still renders.
    """
    if not force_refresh and CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            return [Verb(**item) for item in data]
        except (json.JSONDecodeError, TypeError, OSError):
            pass  # malformed cache — fall through to re-probe

    verbs = _probe_winetricks()
    if not verbs:
        return [Verb(**item) for item in _FALLBACK]

    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps([asdict(v) for v in verbs], indent=2))
    except OSError:
        pass  # cache-write failure is non-fatal
    return verbs


def _probe_winetricks() -> list[Verb]:
    binary = shutil.which("winetricks")
    if not binary:
        return []
    try:
        result = subprocess.run([binary, "--list-all"], capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return parse_list_all(result.stdout)


_CATEGORY_RE = re.compile(r"^=+\s*(\S+)\s*=+\s*$")
_VERB_RE = re.compile(r"^(\S+)\s{2,}(.+?)\s*$")


def parse_list_all(text: str) -> list[Verb]:
    """Parse ``winetricks --list-all`` stdout into a list of :class:`Verb`.

    Category headers look like ``===== dlls =====`` and verb lines have the
    form ``<name><≥2 spaces><description>``.
    """
    current = "misc"
    verbs: list[Verb] = []
    for line in text.splitlines():
        m = _CATEGORY_RE.match(line)
        if m:
            current = m.group(1).lower()
            continue
        m = _VERB_RE.match(line)
        if m:
            verbs.append(Verb(name=m.group(1), category=current, description=m.group(2)))
    return verbs
