"""umu-launcher integration — canonical Proton entry point + ProtonFixes.

``umu-run`` wraps Proton with ProtonFixes per-game lookups (keyed by Steam
AppID) and sets the Steam-compat env vars internally, replacing our hand-rolled
``STEAM_COMPAT_*`` + ``SteamAppId=0`` workaround.

Behaviour:

* No-op when ``umu-run`` is not installed (we fall back to direct Proton).
* No-op for Wine runtimes (umu is Proton-only).
* Can be disabled globally (``Config.use_umu``) or per-app
  (``AppConfig.use_umu``).
"""

from __future__ import annotations

import shutil

from exwin.models import AppEntry


def is_available() -> bool:
    """Return True if ``umu-run`` is on ``PATH``."""
    return shutil.which("umu-run") is not None


def resolve_gameid(app: AppEntry) -> str:
    """Return the ``GAMEID`` umu should use for *app*.

    Prefers the Steam App ID stored on the app (populated by ProtonDB lookup).
    Falls back to ``"0"``, which selects ProtonFixes' generic path.
    """
    if app.steam_appid:
        return str(app.steam_appid)
    return "0"
