"""Auto-configure: recommend and apply the best per-game Wine/Proton settings.

Inspects the installed game (engine markers, DLL names referenced by the main
executable, bundled redistributables) and the host system (GPUs, Vulkan
driver, gamemode) to build an explainable list of setting changes, then
applies them: the per-app config is saved and any prefix-level work (DXVK /
VKD3D-Proton install, new winetricks verbs) is executed.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from exwin.backend import redist_scanner
from exwin.backend.app_config import AppConfig, save_app_config
from exwin.backend.auto_detect import detect_pe_arch
from exwin.backend.config import Config
from exwin.backend.dxvk import install_dxvk, install_vkd3d
from exwin.backend.gpu import detect_gpus, vulkan_available
from exwin.backend.runtime import Runtime
from exwin.backend.winetricks import is_available as winetricks_available
from exwin.backend.winetricks import run_verbs
from exwin.models import AppEntry

# DLL name → winetricks verb for the Visual C++ runtime that ships it.
# vcrun2019 covers the merged 2015-2019 (UCRT/140) family, matching
# redist_scanner's mapping.
_VC_DLL_VERBS: dict[bytes, str] = {
    b"msvcp140.dll": "vcrun2019",
    b"vcruntime140.dll": "vcrun2019",
    b"vcruntime140_1.dll": "vcrun2019",
    b"msvcp120.dll": "vcrun2013",
    b"msvcr120.dll": "vcrun2013",
    b"msvcp110.dll": "vcrun2012",
    b"msvcr110.dll": "vcrun2012",
    b"msvcp100.dll": "vcrun2010",
    b"msvcr100.dll": "vcrun2010",
    b"msvcp90.dll": "vcrun2008",
    b"msvcr90.dll": "vcrun2008",
    b"msvcp80.dll": "vcrun2005",
    b"msvcr80.dll": "vcrun2005",
    b"msvcp71.dll": "vcrun2003",
    b"msvcr71.dll": "vcrun2003",
}

# Graphics-API DLLs referenced by the exe → hint keys.
_GFX_DLL_HINTS: dict[bytes, str] = {
    b"d3d12.dll": "d3d12",
    b"d3d12core.dll": "d3d12",
    b"d3d11.dll": "d3d11",
    b"d3d10.dll": "d3d10",
    b"d3d9.dll": "d3d9",
    b"d3d8.dll": "d3d8",
    b"ddraw.dll": "ddraw",
    b"opengl32.dll": "opengl",
    b"vulkan-1.dll": "vulkan",
}

_DOTNET_DLL = b"mscoree.dll"

# Cap how much of a (potentially huge) exe we scan for DLL-name strings.
_EXE_SCAN_CAP = 256 * 1024 * 1024
_EXE_SCAN_CHUNK = 4 * 1024 * 1024


@dataclass
class GameHints:
    """Facts discovered about an installed game."""

    engine: str = ""  # "unity" | "unreal" | "godot" | "gamemaker" | "renpy" | ""
    graphics: set[str] = field(default_factory=set)  # keys from _GFX_DLL_HINTS
    vc_verbs: list[str] = field(default_factory=list)
    dotnet: bool = False
    exe_arch: str = ""  # "win32" | "win64" | ""


@dataclass
class SettingChange:
    label: str  # e.g. "DXVK"
    value: str  # e.g. "on"
    reason: str


@dataclass
class Recommendation:
    """A proposed AppConfig plus the explainable diff that produced it."""

    config: AppConfig
    changes: list[SettingChange] = field(default_factory=list)
    new_verbs: list[str] = field(default_factory=list)  # verbs to run against the prefix
    install_dxvk: bool = False
    install_vkd3d: bool = False
    hints: GameHints = field(default_factory=GameHints)

    @property
    def is_empty(self) -> bool:
        return not self.changes


# ---------------------------------------------------------------------------
# Game inspection
# ---------------------------------------------------------------------------


def scan_game_hints(install_dir: Path | None, exe_rel: str) -> GameHints:
    """Inspect the game directory and main executable for engine/API/runtime hints."""
    hints = GameHints()
    if not install_dir or not install_dir.is_dir():
        return hints

    exe = (install_dir / exe_rel) if exe_rel else None
    if exe is not None and exe.is_file():
        hints.exe_arch = detect_pe_arch(exe) or ""
        found = _search_file_strings(exe, [*_GFX_DLL_HINTS, *_VC_DLL_VERBS, _DOTNET_DLL])
        hints.graphics = {_GFX_DLL_HINTS[t] for t in found if t in _GFX_DLL_HINTS}
        hints.dotnet = _DOTNET_DLL in found
        for token, verb in _VC_DLL_VERBS.items():
            if token in found and verb not in hints.vc_verbs:
                hints.vc_verbs.append(verb)

    hints.engine = _detect_engine(install_dir, exe)
    # Unity and Unreal render via D3D11 by default; assume it when the exe
    # itself revealed nothing (Unity links d3d11 from UnityPlayer.dll).
    if hints.engine in ("unity", "unreal") and not hints.graphics:
        hints.graphics.add("d3d11")
    return hints


def _detect_engine(install_dir: Path, exe: Path | None) -> str:
    roots = [install_dir]
    if exe is not None and exe.parent != install_dir:
        roots.append(exe.parent)

    for root in roots:
        if (root / "UnityPlayer.dll").is_file() or any(root.glob("*_Data/globalgamemanagers")):
            return "unity"
        if (root / "data.win").is_file():
            return "gamemaker"
        if any(root.glob("*.pck")):
            return "godot"
        if (root / "renpy").is_dir():
            return "renpy"
    if (install_dir / "Engine").is_dir() and any(install_dir.glob("*/Content/Paks/*.pak")):
        return "unreal"
    return ""


def _search_file_strings(path: Path, tokens: list[bytes]) -> set[bytes]:
    """Case-insensitively search *path* for the given ASCII tokens (chunked read)."""
    remaining = {t.lower() for t in tokens}
    found: set[bytes] = set()
    overlap = max(len(t) for t in remaining) - 1 if remaining else 0
    read = 0
    tail = b""
    try:
        with open(path, "rb") as f:
            while remaining and read < _EXE_SCAN_CAP:
                chunk = f.read(_EXE_SCAN_CHUNK)
                if not chunk:
                    break
                read += len(chunk)
                blob = (tail + chunk).lower()
                for token in list(remaining):
                    if token in blob:
                        remaining.discard(token)
                        found.add(token)
                tail = chunk[-overlap:] if overlap else b""
    except OSError:
        pass
    return found


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


def recommend_settings(
    app: AppEntry,
    current: AppConfig,
    runtime: Runtime | None,
) -> Recommendation:
    """Build a recommended AppConfig for *app* with reasons for every change."""
    cfg = replace(
        current,
        winetricks_verbs=list(current.winetricks_verbs),
        env=dict(current.env),
        launch_args=list(current.launch_args),
        dll_overrides=dict(current.dll_overrides),
    )
    rec = Recommendation(config=cfg)
    rec.hints = scan_game_hints(app.install_path, app.exe_path)

    _recommend_gpu(rec, cfg)
    _recommend_translation_layers(rec, cfg, runtime)
    _recommend_launch(rec, cfg)
    _recommend_verbs(rec, cfg, app)
    return rec


def _recommend_gpu(rec: Recommendation, cfg: AppConfig) -> None:
    gpus = detect_gpus()
    nvidia = any(g.vendor == "nvidia" for g in gpus)

    if nvidia and not cfg.nvapi:
        cfg.nvapi = True
        rec.changes.append(
            SettingChange("NVAPI / DLSS", "on", "NVIDIA GPU detected — exposes DLSS to the game.")
        )
    elif not nvidia and cfg.nvapi and gpus:
        cfg.nvapi = False
        rec.changes.append(
            SettingChange("NVAPI / DLSS", "off", "No NVIDIA GPU present — NVAPI has no effect.")
        )

    # Hybrid graphics: default to the discrete GPU when the primary is an iGPU.
    if cfg.gpu_index is None and len(gpus) > 1 and gpus[0].vendor == "intel":
        discrete = next((g for g in gpus[1:] if g.vendor in ("amd", "nvidia")), None)
        if discrete is not None:
            cfg.gpu_index = discrete.index
            rec.changes.append(
                SettingChange(
                    "GPU",
                    discrete.name,
                    "Hybrid graphics — render on the discrete GPU (DRI_PRIME).",
                )
            )


def _recommend_translation_layers(
    rec: Recommendation, cfg: AppConfig, runtime: Runtime | None
) -> None:
    gfx = rec.hints.graphics
    proton = runtime is not None and runtime.is_proton

    if proton:
        if cfg.dxvk or cfg.vkd3d:
            cfg.dxvk = False
            cfg.vkd3d = False
            rec.changes.append(
                SettingChange(
                    "DXVK / VKD3D install",
                    "off",
                    "Proton ships DXVK and VKD3D-Proton built in — no prefix install needed.",
                )
            )
    elif vulkan_available():
        needs_dxvk = not gfx or bool(gfx & {"d3d8", "d3d9", "d3d10", "d3d11"})
        if needs_dxvk and not cfg.dxvk:
            cfg.dxvk = True
            rec.install_dxvk = True
            api = ", ".join(sorted(g for g in gfx if g.startswith("d3d") and g != "d3d12")) or (
                "DirectX"
            )
            rec.changes.append(
                SettingChange("DXVK", "on", f"Game uses {api} — translate to Vulkan for speed.")
            )
        if "d3d12" in gfx and not cfg.vkd3d:
            cfg.vkd3d = True
            rec.install_vkd3d = True
            rec.changes.append(
                SettingChange(
                    "VKD3D-Proton", "on", "Game uses DirectX 12 — required on plain Wine."
                )
            )

    if (cfg.dxvk or proton) and not cfg.dxvk_state_cache:
        cfg.dxvk_state_cache = True
        rec.changes.append(
            SettingChange(
                "Per-app shader cache",
                "on",
                "Keeps the DXVK state cache with this game's prefix (less re-stutter).",
            )
        )


def _recommend_launch(rec: Recommendation, cfg: AppConfig) -> None:
    if not cfg.gamemode and shutil.which("gamemoderun"):
        cfg.gamemode = True
        rec.changes.append(
            SettingChange(
                "Gamemode", "on", "gamemode is installed — improves CPU scheduling while playing."
            )
        )


def _recommend_verbs(rec: Recommendation, cfg: AppConfig, app: AppEntry) -> None:
    wanted: list[tuple[str, str]] = []  # (verb, reason)

    for verb in rec.hints.vc_verbs:
        wanted.append(
            (verb, "The main executable links this Visual C++ runtime — install it via winetricks.")
        )

    # Bundled redistributables the publisher shipped (Steam would auto-run these).
    if app.install_path is not None:
        try:
            findings = redist_scanner.scan(app.install_path)
        except OSError:
            findings = []
        for finding in findings:
            if finding.action == "verb" and finding.recommended:
                wanted.append((finding.payload, f"Bundled prerequisite: {finding.description}."))

    for verb, reason in wanted:
        if verb in cfg.winetricks_verbs or verb in rec.new_verbs:
            continue
        rec.new_verbs.append(verb)
        rec.changes.append(SettingChange("Winetricks", f"+ {verb}", reason))
    cfg.winetricks_verbs = [*cfg.winetricks_verbs, *rec.new_verbs]

    if rec.new_verbs and not winetricks_available():
        rec.new_verbs = []
        rec.changes.append(
            SettingChange(
                "Winetricks",
                "not installed",
                "Verbs were added to the config but can't be applied until "
                "winetricks is installed.",
            )
        )


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


def apply_recommendation(
    app: AppEntry,
    rec: Recommendation,
    config: Config,
    runtime: Runtime | None,
    on_progress: Callable[[str], None] | None = None,
) -> list[str]:
    """Persist the recommended config and run prefix-level work.

    Returns a list of non-fatal problem messages (empty = everything applied).
    """

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    problems: list[str] = []

    _log("Saving settings…")
    save_app_config(app.app_id, config, rec.config)

    p_root = app.prefix_path
    if p_root is None:
        if rec.install_dxvk or rec.install_vkd3d or rec.new_verbs:
            problems.append("No Wine prefix yet — prefix-level changes were skipped.")
        return problems

    if rec.install_dxvk:
        try:
            install_dxvk(p_root, runtime, on_progress=_log)
        except Exception as exc:
            problems.append(f"DXVK install failed: {exc}")

    if rec.install_vkd3d:
        try:
            install_vkd3d(p_root, runtime, on_progress=_log)
        except Exception as exc:
            problems.append(f"vkd3d-proton install failed: {exc}")

    if rec.new_verbs:
        if not winetricks_available():
            problems.append("winetricks not found — verbs were not applied.")
        else:
            _log(f"Applying winetricks: {' '.join(rec.new_verbs)}")
            try:
                proc = run_verbs(p_root, rec.new_verbs, runtime)
                rc = proc.wait()
                if rc != 0:
                    problems.append(f"winetricks exited with code {rc} — check the logs.")
            except Exception as exc:
                problems.append(f"winetricks failed: {exc}")

    _log("Auto-configure complete.")
    return problems
