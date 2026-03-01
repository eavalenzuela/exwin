"""DXVK and VKD3D-Proton installation into Wine prefixes."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

from exwin.backend.runtime import Runtime
from exwin.backend.winetricks import is_available as winetricks_available
from exwin.backend.winetricks import run_verbs

_VKD3D_RELEASES_URL = "https://api.github.com/repos/HansKristian-Work/vkd3d-proton/releases/latest"


def install_dxvk(
    prefix_root: Path,
    runtime: Runtime | None,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Install DXVK into *prefix_root* via winetricks."""

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    if not winetricks_available():
        raise RuntimeError("winetricks is required to install DXVK but was not found")

    _log("Installing DXVK via winetricks…")
    proc = run_verbs(prefix_root, ["dxvk"], runtime)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"winetricks dxvk failed (exit code {proc.returncode})")
    _log("DXVK installed.")


def install_vkd3d(
    prefix_root: Path,
    runtime: Runtime | None,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Install vkd3d-proton into *prefix_root*.

    Downloads the latest release tarball from GitHub, extracts it to a temp
    directory, and runs ``setup_vkd3d_proton.sh install``.  Falls back to
    ``winetricks vkd3d_proton`` if the setup script is unavailable.
    """

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    _log("Fetching latest vkd3d-proton release info…")
    try:
        release = _get_latest_vkd3d_release()
        asset = _find_tarball_asset(release)
    except Exception as exc:
        _log(f"Could not fetch vkd3d-proton release: {exc} — trying winetricks fallback")
        _install_vkd3d_via_winetricks(prefix_root, runtime, on_progress)
        return

    tag = release.get("tag_name", "")
    _log(f"Downloading vkd3d-proton {tag}…")

    with tempfile.TemporaryDirectory() as tmpdir:
        tarball_path = Path(tmpdir) / asset["name"]
        _download_file(asset["browser_download_url"], tarball_path)
        _log(f"Extracting {asset['name']}…")
        extract_dir = Path(tmpdir) / "vkd3d-proton"
        extract_dir.mkdir()
        with tarfile.open(tarball_path) as tf:
            tf.extractall(extract_dir)

        # The tarball extracts to a single directory; find setup script inside it
        setup_script = _find_setup_script(extract_dir)
        if setup_script is None:
            _log("setup_vkd3d_proton.sh not found — trying winetricks fallback")
            _install_vkd3d_via_winetricks(prefix_root, runtime, on_progress)
            return

        # Make the script executable
        setup_script.chmod(setup_script.stat().st_mode | stat.S_IEXEC)

        env = os.environ.copy()
        if runtime and runtime.is_proton:
            env["WINEPREFIX"] = str(prefix_root / "pfx")
        else:
            env["WINEPREFIX"] = str(prefix_root)

        _log("Running setup_vkd3d_proton.sh install…")
        result = subprocess.run(
            [str(setup_script), "install"],
            env=env,
            cwd=str(setup_script.parent),
        )
        if result.returncode != 0:
            raise RuntimeError(f"setup_vkd3d_proton.sh failed (exit code {result.returncode})")

    _log("vkd3d-proton installed.")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_latest_vkd3d_release() -> dict:
    req = urllib.request.Request(
        _VKD3D_RELEASES_URL,
        headers={"User-Agent": "exwin/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _find_tarball_asset(release: dict) -> dict:
    for asset in release.get("assets", []):
        name: str = asset.get("name", "")
        if name.endswith(".tar.zst") or name.endswith(".tar.gz"):
            return asset
    raise RuntimeError("No tarball asset found in vkd3d-proton release")


def _download_file(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "exwin/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        while chunk := resp.read(65536):
            f.write(chunk)


def _find_setup_script(extract_dir: Path) -> Path | None:
    for p in extract_dir.rglob("setup_vkd3d_proton.sh"):
        return p
    return None


def _install_vkd3d_via_winetricks(
    prefix_root: Path,
    runtime: Runtime | None,
    on_progress: Callable[[str], None] | None,
) -> None:
    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    if not winetricks_available():
        raise RuntimeError("winetricks is required for the vkd3d-proton fallback but was not found")
    _log("Installing vkd3d-proton via winetricks…")
    proc = run_verbs(prefix_root, ["vkd3d_proton"], runtime)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"winetricks vkd3d_proton failed (exit code {proc.returncode})")
    _log("vkd3d-proton installed.")
