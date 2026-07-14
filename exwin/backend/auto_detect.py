"""Auto-detection install route: inspect installer file(s) and plan the best install.

Looks at magic bytes, PE headers, embedded installer-tech markers, and sibling
part files to decide *how* a given file should be installed (innoextract
extraction, direct archive extraction, or an interactive Wine install), then
picks sensible defaults (runtime, prefix architecture, translation layers) so
the whole install can run with a single click.  Pure analysis — nothing here
mutates the system.
"""

from __future__ import annotations

import re
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from exwin.backend.archive_installer import (
    archive_tool_available,
    detect_archive_type,
    detect_sfx_archive,
)
from exwin.backend.gog_installer import (
    InstallerInfo,
    find_innoextract,
    find_rar_tool,
    find_sibling_parts,
    probe,
)
from exwin.backend.gpu import vulkan_available
from exwin.backend.runtime import Runtime

# How much of the file head to scan for embedded tech markers.  Installer
# stubs (InnoSetup, NSIS, InstallShield, SFX modules) all identify themselves
# within the first few hundred KiB.
_HEAD_SCAN_BYTES = 8 * 1024 * 1024

# Human-readable labels for detected installer technologies.
TECH_LABELS = {
    "innosetup": "InnoSetup installer",
    "innosetup-gog": "GOG offline installer (InnoSetup)",
    "nsis": "NSIS installer",
    "installshield": "InstallShield installer",
    "setup-factory": "Setup Factory installer",
    "wise": "Wise installer",
    "msi": "Windows Installer package (MSI)",
    "zip": "ZIP archive",
    "7z": "7-Zip archive",
    "rar": "RAR archive",
    "rar-sfx": "Self-extracting RAR archive",
    "7z-sfx": "Self-extracting 7-Zip archive",
    "unknown": "Windows executable (unrecognised installer)",
}

ROUTE_LABELS = {
    "gog": "Extract with innoextract — no Windows installer runs",
    "archive": "Extract the archive directly — no Windows installer runs",
    "generic": "Run the installer interactively via Wine/Proton",
}

# Marker → tech, checked in order (first hit wins) against the lowercased head.
_TECH_MARKERS: list[tuple[bytes, str]] = [
    (b"inno setup", "innosetup"),
    (b"nullsoft", "nsis"),
    (b"installshield", "installshield"),
    (b"setup factory", "setup-factory"),
    (b"wise installation", "wise"),
]


@dataclass
class InstallPlan:
    """Everything the install dialog needs to run an install without questions."""

    installer_path: Path
    route: str  # "gog" | "archive" | "generic"
    tech: str  # key into TECH_LABELS
    title: str
    arch: str = "win64"
    game_id: str = ""
    languages: list[str] = field(default_factory=list)
    probe_info: InstallerInfo | None = None
    archive_kind: str = ""  # "zip" | "7z" | "rar" when route == "archive"
    parts: list[Path] = field(default_factory=list)
    runtime_index: int | None = None
    runtime_name: str = ""
    dxvk: bool = False
    vkd3d: bool = False
    winetricks_verbs: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False  # a required tool is missing — install cannot proceed

    @property
    def tech_label(self) -> str:
        label = TECH_LABELS.get(self.tech, self.tech)
        if self.parts:
            label += f" — {1 + len(self.parts)} parts"
        return label

    @property
    def route_label(self) -> str:
        return ROUTE_LABELS.get(self.route, self.route)


# ---------------------------------------------------------------------------
# Low-level probes
# ---------------------------------------------------------------------------


def detect_pe_arch(path: Path) -> str | None:
    """Return ``"win32"``/``"win64"`` from the PE header, or None if not a PE file."""
    try:
        with open(path, "rb") as f:
            head = f.read(0x40)
            if len(head) < 0x40 or head[:2] != b"MZ":
                return None
            e_lfanew = struct.unpack_from("<I", head, 0x3C)[0]
            f.seek(e_lfanew)
            pe = f.read(6)
    except (OSError, struct.error):
        return None
    if len(pe) < 6 or pe[:4] != b"PE\x00\x00":
        return None
    machine = struct.unpack_from("<H", pe, 4)[0]
    if machine == 0x014C:  # IMAGE_FILE_MACHINE_I386
        return "win32"
    if machine in (0x8664, 0xAA64):  # AMD64 / ARM64
        return "win64"
    return None


def detect_installer_tech(path: Path) -> str:
    """Identify the installer technology from markers embedded in the stub."""
    try:
        with open(path, "rb") as f:
            head = f.read(_HEAD_SCAN_BYTES).lower()
    except OSError:
        return "unknown"
    for marker, tech in _TECH_MARKERS:
        if marker in head:
            return tech
    return "unknown"


def find_archive_parts(path: Path) -> list[Path]:
    """Return sibling volumes of a multi-part archive set, excluding *path* itself.

    Recognises WinRAR ``name.partN.rar``/``name.partN.exe`` naming and the old
    ``name.rar`` + ``name.r00``/``name.r01`` scheme.
    """
    stem = path.stem  # "Game.part1.exe" → "Game.part1"
    base = re.sub(r"[._\- ]part\d+$", "", stem, flags=re.IGNORECASE)
    parts: set[Path] = set()
    if base != stem:
        for sibling in path.parent.glob(f"{base}*"):
            if sibling == path:
                continue
            if re.fullmatch(
                rf"{re.escape(base)}[._\- ]part\d+\.(rar|exe)", sibling.name, re.IGNORECASE
            ):
                parts.add(sibling)
    for sibling in path.parent.glob(f"{stem}.r[0-9][0-9]"):
        if sibling != path:
            parts.add(sibling)
    return sorted(parts)


def clean_title(stem: str) -> str:
    """Derive a display name from an installer filename stem."""
    s = re.sub(r"^(setup|install(er)?)[._\- ]+", "", stem, flags=re.IGNORECASE)
    s = re.sub(r"[._\- ]?part[._\- ]?\d+$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[._\- ]?v?\d+(\.\d+)+[a-z]?$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[._]+", " ", s).strip(" -_")
    if s and s == s.lower():
        s = s.title()
    return s or stem


def pick_runtime(runtimes: list[Runtime]) -> tuple[int | None, str]:
    """Pick the best runtime: newest Proton-GE, else newest Proton, else Wine.

    Returns ``(index into runtimes, reason)``; ``(None, reason)`` when empty.
    """
    if not runtimes:
        return None, "No Wine/Proton runtime detected — configure one first."

    def _rank(rt: Runtime) -> tuple:
        blob = f"{rt.name} {rt.version}".lower()
        is_ge = "ge-proton" in blob or "proton-ge" in blob
        version = tuple(int(n) for n in re.findall(r"\d+", blob)[:4])
        return (rt.is_proton, is_ge, version)

    best = max(range(len(runtimes)), key=lambda i: _rank(runtimes[i]))
    rt = runtimes[best]
    if not rt.is_proton:
        reason = f"{rt.name} is the only kind of runtime available."
    elif "ge-proton" in rt.name.lower() or "proton-ge" in rt.name.lower():
        reason = f"{rt.name} — newest Proton-GE build (includes community game fixes)."
    else:
        reason = f"{rt.name} — newest Proton runtime detected."
    return best, reason


# ---------------------------------------------------------------------------
# Plan assembly
# ---------------------------------------------------------------------------


def analyze_installer(installer_path: Path, runtimes: list[Runtime]) -> InstallPlan:
    """Inspect *installer_path* and return a complete :class:`InstallPlan`."""
    plan = _classify(installer_path)
    _pick_defaults(plan, runtimes)
    return plan


def _classify(path: Path) -> InstallPlan:
    """Decide route + tech + title from the file itself."""
    # MSI: no reliable direct-extraction path — run it via Wine's msiexec.
    if path.suffix.lower() == ".msi":
        plan = InstallPlan(path, route="generic", tech="msi", title=clean_title(path.stem))
        plan.reasons.append("MSI packages are installed by Wine's built-in msiexec.")
        return plan

    # Plain archive (zip/7z/rar by magic bytes).
    kind = detect_archive_type(path)
    if kind is not None:
        plan = InstallPlan(
            path,
            route="archive",
            tech=kind,
            title=clean_title(path.stem),
            archive_kind=kind,
            parts=find_archive_parts(path),
        )
        plan.reasons.append("Archives are extracted directly; no Windows installer needs to run.")
        _require_archive_tool(plan, kind)
        return plan

    # InnoSetup (GOG offline installers and many others) → innoextract.
    inno_checked = False
    is_inno = False
    try:
        binary = find_innoextract()
        inno_checked = True
        result = subprocess.run(
            [binary, "--data-version", str(path)], capture_output=True, timeout=15
        )
        is_inno = result.returncode == 0
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        pass
    if is_inno:
        try:
            info = probe(path)
        except Exception:
            info = InstallerInfo(title=clean_title(path.stem), game_id="", setup_version="")
        plan = InstallPlan(
            path,
            route="gog",
            tech="innosetup-gog" if info.game_id else "innosetup",
            title=info.title,
            game_id=info.game_id,
            languages=info.languages,
            probe_info=info,
            parts=find_sibling_parts(path),
        )
        if info.game_id:
            plan.reasons.append(
                "GOG offline installer — extracting with innoextract skips the "
                "Windows setup wizard entirely."
            )
        else:
            plan.reasons.append("InnoSetup installer — contents can be extracted directly.")
        if plan.parts and find_rar_tool() is None:
            plan.warnings.append(
                "Multi-part installer needs 'unrar' or 'unar' to unpack the .bin parts."
            )
            plan.blocked = True
        return plan

    # Self-extracting archive (.exe with an embedded RAR/7z payload).
    sfx_kind = detect_sfx_archive(path)
    if sfx_kind is not None:
        parts = find_archive_parts(path)
        tech = f"{sfx_kind}-sfx"
        if parts or sfx_kind == "rar":
            plan = InstallPlan(
                path,
                route="archive",
                tech=tech,
                title=clean_title(path.stem),
                archive_kind=sfx_kind,
                parts=parts,
            )
            plan.reasons.append(
                "Self-extracting archive — the payload can be unpacked directly "
                "without running the Windows stub."
            )
            _require_archive_tool(plan, sfx_kind)
            return plan
        # Single-file 7z SFX is a common wrapper for real installers — run it.
        plan = InstallPlan(path, route="generic", tech=tech, title=clean_title(path.stem))
        plan.reasons.append(
            "Self-extracting installer — runs interactively so any embedded setup script executes."
        )
        return plan

    # Fall back: interactive Wine install, with the stub tech as a hint.
    tech = detect_installer_tech(path)
    plan = InstallPlan(path, route="generic", tech=tech, title=clean_title(path.stem))
    if tech != "unknown":
        plan.reasons.append(
            f"{TECH_LABELS[tech]} — no direct extraction path; the installer "
            "runs interactively via Wine."
        )
    else:
        plan.reasons.append("Unrecognised installer — it will run interactively via Wine.")
    if not inno_checked:
        plan.warnings.append("innoextract not installed — could not check for InnoSetup/GOG.")
    return plan


def _require_archive_tool(plan: InstallPlan, kind: str) -> None:
    if archive_tool_available(kind):
        return
    tool = "p7zip (7z)" if kind == "7z" else "'unar' or 'unrar'"
    plan.warnings.append(f"Extracting this archive requires {tool} — install it to continue.")
    plan.blocked = True


def _pick_defaults(plan: InstallPlan, runtimes: list[Runtime]) -> None:
    """Fill in runtime, arch, and translation-layer defaults."""
    idx, reason = pick_runtime(runtimes)
    plan.runtime_index = idx
    plan.reasons.append(reason)
    runtime = runtimes[idx] if idx is not None else None
    if runtime is not None:
        plan.runtime_name = runtime.name

    plan.arch = "win64"
    pe_arch = detect_pe_arch(plan.installer_path)
    if pe_arch == "win32":
        plan.reasons.append(
            "64-bit prefix (runs 32-bit software too; the installer stub is 32-bit)."
        )
    else:
        plan.reasons.append("64-bit prefix (runs both 32- and 64-bit software).")

    if runtime is None:
        return
    if runtime.is_proton:
        plan.dxvk = False
        plan.vkd3d = False
        plan.reasons.append("Proton ships DXVK and VKD3D-Proton built in — nothing to install.")
    elif vulkan_available():
        plan.dxvk = True
        plan.reasons.append(
            "Vulkan driver detected — DXVK will translate DirectX 9-11 for plain Wine."
        )
    else:
        plan.warnings.append(
            "No Vulkan driver detected — DirectX games may fall back to slow rendering."
        )
