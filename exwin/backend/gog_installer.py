"""GOG offline installer probing, extraction, and metadata parsing."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# Pre-compiled patterns used in _parse_info_output (called per-line)
_RE_INSPECTING = re.compile(r'Inspecting "(.+?)"')
_RE_DATA_VERSION = re.compile(r"setup data version ([\d.]+)")
_RE_GAME_ID = re.compile(r"GOG\.com game ID is (\d+)")
_RE_LANGUAGE = re.compile(r"\s+-\s+([a-z]{2}-[A-Z]{2})")

# Pattern used in guess_exe and app_id_from_info
_RE_NON_WORD = re.compile(r"\W+")


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


def find_rar_tool() -> str | None:
    """Return the path to unrar or unar if available, else None."""
    for tool in ("unrar", "unar"):
        path = shutil.which(tool)
        if path:
            return path
    return None


def count_files(installer_path: Path) -> int:
    """Count the number of files in the installer via innoextract --list.

    Returns 0 if counting fails (progress will fall back to unbounded).
    """
    binary = find_innoextract()
    try:
        result = subprocess.run(
            [binary, "--list", "--gog", str(installer_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Each extractable file has a line starting with " - "
        return sum(1 for line in result.stdout.splitlines() if line.startswith(" - "))
    except Exception:
        return 0


def extract(
    installer_path: Path,
    output_dir: Path,
    on_progress: Callable[[str], None] | None = None,
    on_file_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Extract the installer contents to output_dir, streaming progress lines.

    Passes --gog so innoextract also processes GOG-specific RAR-format .bin
    part files (requires unrar or unar on PATH).

    If *on_file_progress* is set and *total* was pre-counted, it is called
    with ``(current_file_number, total_files)`` for each extracted file.
    """
    binary = find_innoextract()
    output_dir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [binary, "--gog", "--extract", "--output-dir", str(output_dir), str(installer_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert proc.stdout is not None
    file_count = 0
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        if on_progress:
            on_progress(line)
        # innoextract prints "Extracting ..." for each file
        if line.startswith("Extracting") or line.startswith(" - "):
            file_count += 1
            if on_file_progress:
                on_file_progress(file_count, 0)

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"innoextract exited with code {proc.returncode}")


def parse_game_info(install_dir: Path) -> dict:
    """Parse the goggame-*.info JSON placed in install_dir by innoextract.

    Checks install_dir/, app/ (InnoSetup single-part layout), and game/
    (GOG RAR-part layout produced by the unar / 7z extraction path).
    """
    for subdir in (install_dir, install_dir / "app", install_dir / "game"):
        for info_file in subdir.glob("goggame-*.info"):
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
        hint_slug = _RE_NON_WORD.sub("", hint.lower())
        for exe in pool:
            if _RE_NON_WORD.sub("", exe.stem.lower()) in hint_slug:
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


def find_hashdb(installer_path: Path) -> Path | None:
    """Return the .hashdb sidecar path if it exists alongside the installer."""
    candidate = installer_path.with_suffix(".hashdb")
    return candidate if candidate.exists() else None


def validate_checksums(
    installer_path: Path,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Verify MD5 of each installer part listed in the .hashdb sidecar.

    No-op if .hashdb not found. Raises RuntimeError on mismatch or missing file.
    """
    hashdb = find_hashdb(installer_path)
    if hashdb is None:
        return

    entries: dict[str, str] = {}
    for line in hashdb.read_text(encoding="utf-8").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            entries[parts[1].strip()] = parts[0].lower()

    parent = installer_path.parent
    for filename, expected in entries.items():
        path = parent / filename
        if not path.exists():
            raise RuntimeError(f"Missing installer file: {filename}")
        if on_progress:
            on_progress(f"Verifying {filename}…")
        if _md5_file(path) != expected:
            raise RuntimeError(
                f"Checksum mismatch for {filename} — file may be corrupt or incomplete"
            )


def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def app_id_from_info(info: InstallerInfo) -> str:
    """Derive a stable, filesystem-safe app ID for a GOG game."""
    if info.game_id:
        return f"gog-{info.game_id}"
    # Fallback: slugify the title
    slug = _RE_NON_WORD.sub("-", info.title.lower()).strip("-")
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
        m = _RE_INSPECTING.match(line)
        if m:
            title = m.group(1)

        m = _RE_DATA_VERSION.search(line)
        if m:
            setup_version = m.group(1)

        m = _RE_GAME_ID.match(line.strip())
        if m:
            game_id = m.group(1)

        m = _RE_LANGUAGE.match(line)
        if m:
            languages.append(m.group(1))

    return InstallerInfo(
        title=title,
        game_id=game_id,
        setup_version=setup_version,
        languages=languages,
        installer_path=str(installer_path),
    )
