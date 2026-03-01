"""GOG offline installer probing, extraction, and metadata parsing."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class InstallerInfo:
    """Metadata extracted from a GOG installer via innoextract --info."""

    title: str
    game_id: str  # GOG numeric game ID, empty string if not a GOG installer
    setup_version: str
    languages: list[str] = field(default_factory=list)
    installer_path: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_innoextract() -> str:
    """Return the path to the innoextract binary, or raise RuntimeError."""
    candidates = [
        shutil.which("innoextract"),
        str(Path.home() / ".local" / "bin" / "innoextract"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    raise RuntimeError(
        "innoextract not found.\n"
        "Install it with: apt install innoextract\n"
        "Or download from https://constexpr.org/innoextract/"
    )


def probe(installer_path: Path) -> InstallerInfo:
    """Run 'innoextract --info' and return parsed metadata."""
    binary = find_innoextract()
    result = subprocess.run(
        [binary, "--info", str(installer_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout + result.stderr
    return _parse_info_output(output, installer_path)


def extract(
    installer_path: Path,
    output_dir: Path,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Extract the installer contents to output_dir, streaming progress lines."""
    binary = find_innoextract()
    output_dir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [binary, "--extract", "--output-dir", str(output_dir), str(installer_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if line and on_progress:
            on_progress(line)

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"innoextract exited with code {proc.returncode}")


def parse_game_info(install_dir: Path) -> dict:
    """Parse the goggame-*.info JSON placed in install_dir by innoextract."""
    for info_file in install_dir.glob("goggame-*.info"):
        try:
            return json.loads(info_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    # Also check app/ subdirectory (some GOG installers use it)
    for info_file in (install_dir / "app").glob("goggame-*.info"):
        try:
            return json.loads(info_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return {}


def find_primary_exe(game_info: dict) -> str | None:
    """Return the primary executable path from goggame-*.info playTasks."""
    tasks = game_info.get("playTasks", [])
    # Prefer the task marked isPrimary
    for task in tasks:
        if task.get("isPrimary") and task.get("type") == "FileTask":
            return task.get("path")
    # Fall back to any FileTask
    for task in tasks:
        if task.get("type") == "FileTask":
            return task.get("path")
    return None


def guess_exe(install_dir: Path, hint: str = "") -> str | None:
    """Heuristic fallback: find the most likely main .exe in install_dir."""
    _SKIP = {"__redist", "uninstall", "setup", "vcredist", "dotnet", "isisetup"}

    candidates = [
        p for p in install_dir.rglob("*.exe") if not any(skip in str(p).lower() for skip in _SKIP)
    ]
    if not candidates:
        return None

    # Prefer executables directly in the install root
    root_exes = [p for p in candidates if p.parent == install_dir]
    pool = root_exes if root_exes else candidates

    # Prefer an exe whose stem fuzzy-matches the game title hint
    if hint:
        hint_slug = re.sub(r"\W+", "", hint.lower())
        for exe in pool:
            if re.sub(r"\W+", "", exe.stem.lower()) in hint_slug:
                return str(exe.relative_to(install_dir))

    return str(pool[0].relative_to(install_dir))


def find_cover_art(install_dir: Path) -> Path | None:
    """Return the best portrait cover art found in the installer's tmp/ dir."""
    tmp_dir = install_dir / "tmp"
    if not tmp_dir.is_dir():
        return None

    # GOG embeds portrait cover art as <product_id>_english.jpg
    # These are typically ~150-200 KB; landscape backgrounds are 300 KB+
    english_covers = sorted(tmp_dir.glob("*_english.jpg"), key=lambda p: p.stat().st_size)
    if english_covers:
        # Smallest *_english.jpg tends to be the portrait cover, not the background
        return english_covers[0]

    # Fall back: any jpg that isn't explicitly named "background"
    others = [
        p
        for p in sorted(tmp_dir.glob("*.jpg"), key=lambda p: p.stat().st_size)
        if "background" not in p.name.lower()
    ]
    return others[0] if others else None


def find_sibling_parts(exe_path: Path) -> list[Path]:
    """Return .bin part files that belong to a multi-part GOG installer.

    Looks for files in the same directory matching the pattern:
      <stem>*.bin  (e.g. setup_balrum-1.bin, setup_balrum-2.bin)
    Returns them sorted; empty list for single-part installers.
    """
    stem = exe_path.stem
    parent = exe_path.parent
    return sorted(parent.glob(f"{stem}*.bin"))


def app_id_from_info(info: InstallerInfo) -> str:
    """Derive a stable, filesystem-safe app ID for a GOG game."""
    if info.game_id:
        return f"gog-{info.game_id}"
    # Fallback: slugify the title
    slug = re.sub(r"\W+", "-", info.title.lower()).strip("-")
    return f"gog-{slug}"


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _parse_info_output(output: str, installer_path: Path) -> InstallerInfo:
    title = installer_path.stem
    game_id = ""
    setup_version = ""
    languages: list[str] = []

    for line in output.splitlines():
        m = re.match(r'Inspecting "(.+?)"', line)
        if m:
            title = m.group(1)

        m = re.search(r"setup data version ([\d.]+)", line)
        if m:
            setup_version = m.group(1)

        m = re.match(r"GOG\.com game ID is (\d+)", line.strip())
        if m:
            game_id = m.group(1)

        m = re.match(r"\s+-\s+([a-z]{2}-[A-Z]{2})", line)
        if m:
            languages.append(m.group(1))

    return InstallerInfo(
        title=title,
        game_id=game_id,
        setup_version=setup_version,
        languages=languages,
        installer_path=str(installer_path),
    )
