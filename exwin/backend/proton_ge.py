"""Download and install Proton-GE releases from GitHub."""

from __future__ import annotations

import json
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

_RELEASES_URL = "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases/latest"
_ALL_RELEASES_URL = (
    "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases?per_page=10"
)
_DEFAULT_DEST = Path.home() / ".steam" / "root" / "compatibilitytools.d"


def get_latest_release() -> dict:
    """Return the latest Proton-GE release dict from the GitHub API."""
    req = urllib.request.Request(_RELEASES_URL, headers={"User-Agent": "exwin/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def get_recent_releases(n: int = 5) -> list[dict]:
    """Return the *n* most recent Proton-GE releases."""
    req = urllib.request.Request(_ALL_RELEASES_URL, headers={"User-Agent": "exwin/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        releases = json.loads(resp.read().decode())
    return releases[:n]


def find_ge_proton_asset(release: dict) -> dict:
    """Return the .tar.gz asset from a release, excluding checksums."""
    for asset in release.get("assets", []):
        name: str = asset.get("name", "")
        if name.endswith(".tar.gz") and not name.endswith(".sha512sum"):
            return asset
    raise RuntimeError(f"No .tar.gz asset found in release {release.get('tag_name', '?')}")


def download_and_install(
    release: dict,
    dest_dir: Path = _DEFAULT_DEST,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Download and extract a Proton-GE release into *dest_dir*.

    *on_progress* is called with ``(bytes_downloaded, total_bytes)`` during
    the download.  ``total_bytes`` may be 0 if the server omits Content-Length.

    Returns the path to the extracted Proton-GE directory.
    """
    asset = find_ge_proton_asset(release)
    dest_dir.mkdir(parents=True, exist_ok=True)

    tag = release.get("tag_name", asset["name"])
    extract_dest = dest_dir / tag

    if extract_dest.exists():
        raise RuntimeError(f"{tag} is already installed at {extract_dest}")

    url = asset["browser_download_url"]
    total = asset.get("size", 0)

    with tempfile.TemporaryDirectory() as tmpdir:
        tarball = Path(tmpdir) / asset["name"]

        req = urllib.request.Request(url, headers={"User-Agent": "exwin/1.0"})
        downloaded = 0
        with urllib.request.urlopen(req, timeout=300) as resp, open(tarball, "wb") as f:
            while chunk := resp.read(65536):
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)

        with tarfile.open(tarball) as tf:
            resolved_dest = dest_dir.resolve()
            for member in tf.getmembers():
                target = (dest_dir / member.name).resolve()
                if not target.is_relative_to(resolved_dest):
                    raise RuntimeError(f"Tar path traversal blocked: {member.name}")
            tf.extractall(dest_dir)

    # The tarball should have extracted to a directory named after the tag
    if not extract_dest.exists():
        # Some releases use a slightly different directory name; find what was extracted
        candidates = [p for p in dest_dir.iterdir() if p.is_dir() and tag.lower() in p.name.lower()]
        if candidates:
            return candidates[0]
        raise RuntimeError(f"Could not locate extracted directory for {tag} in {dest_dir}")

    return extract_dest


def is_installed(tag: str, dest_dir: Path = _DEFAULT_DEST) -> bool:
    """Return True if a Proton-GE release with *tag* is already present."""
    return (dest_dir / tag).exists()
