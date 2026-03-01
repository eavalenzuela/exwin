"""Fetch game metadata from the GOG products API and apply it to a library entry."""

from __future__ import annotations

import json
import re
import shutil
import urllib.request
from collections.abc import Callable
from pathlib import Path

from exwin.backend.config import Config
from exwin.db.apps import update_cover_art, update_description

_GOG_PRODUCTS_URL = "https://api.gog.com/products/{game_id}?expand=description,screenshots"
_TIMEOUT = 15


def fetch_metadata(game_id: str) -> dict:
    """GET GOG products API and return a dict with title, description, cover_url.

    Returns an empty dict on any network or parse failure.
    """
    if not game_id:
        return {}

    url = _GOG_PRODUCTS_URL.format(game_id=game_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "exwin/1.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return {}

    images = data.get("images", {})
    # GOG image URLs are protocol-relative ("//images-1.gog-statics.com/...")
    cover_url = images.get("logo") or images.get("sidebarLogo") or ""
    if cover_url.startswith("//"):
        cover_url = "https:" + cover_url

    description_html = (data.get("description") or {}).get("full") or ""
    description = _strip_html(description_html)

    return {
        "title": data.get("title", ""),
        "description": description,
        "cover_url": cover_url,
    }


def apply_metadata(
    app_id: str,
    game_id: str,
    config: Config,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Fetch GOG metadata and persist description + cover art updates to the DB."""

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    _log("Fetching metadata from GOG…")
    meta = fetch_metadata(game_id)
    if not meta:
        _log("No metadata returned from GOG API.")
        return

    if meta.get("description"):
        update_description(app_id, meta["description"])
        _log("Description updated.")

    cover_url = meta.get("cover_url", "")
    if cover_url:
        meta_dir = config.metadata_dir / app_id
        meta_dir.mkdir(parents=True, exist_ok=True)
        cover_dst = meta_dir / "cover.jpg"
        try:
            _download_image(cover_url, cover_dst)
            update_cover_art(app_id, str(cover_dst))
            _log("Cover art updated from GOG CDN.")
        except Exception as exc:
            _log(f"Cover art download failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _download_image(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "exwin/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def apply_custom_cover_art(app_id: str, source: str, config: Config) -> str:
    """Copy a local image or download a URL as the cover art for *app_id*.

    Caches to ``~/.local/share/exwin/metadata/{app_id}/cover.jpg``.
    Updates the DB and returns the destination path string.
    """
    meta_dir = config.metadata_dir / app_id
    meta_dir.mkdir(parents=True, exist_ok=True)
    dst = meta_dir / "cover.jpg"

    if source.startswith("data:image/"):
        import base64

        try:
            _header, b64data = source.split(",", 1)
            image_bytes = base64.b64decode(b64data)
        except Exception as exc:
            raise ValueError(f"Invalid base64 image data: {exc}") from exc
        dst.write_bytes(image_bytes)
    elif source.startswith(("http://", "https://")):
        _download_image(source, dst)
    else:
        src = Path(source)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {source}")
        shutil.copy2(src, dst)

    update_cover_art(app_id, str(dst))
    return str(dst)
