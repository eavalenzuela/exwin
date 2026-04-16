"""App launch pipeline — build env, spawn process, track running state."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from gi.repository import GLib

from exwin.backend.app_config import AppConfig, GamescopeConfig
from exwin.backend.config import Config
from exwin.backend.gpu import detect_gpus
from exwin.backend.runtime import Runtime
from exwin.models import AppEntry

# Cached GPU list — scanned once on first launch that needs GPU selection.
_GPUS: list | None = None


def _build_gamescope_prefix(gs: GamescopeConfig) -> list[str]:
    """Build the ``gamescope … --`` prefix that wraps the real launch cmd."""
    cmd = ["gamescope"]
    if gs.output_width:
        cmd += ["-W", str(gs.output_width)]
    if gs.output_height:
        cmd += ["-H", str(gs.output_height)]
    if gs.game_width:
        cmd += ["-w", str(gs.game_width)]
    if gs.game_height:
        cmd += ["-h", str(gs.game_height)]
    if gs.fullscreen:
        cmd += ["-f"]
    if gs.upscale_filter:
        cmd += ["-F", gs.upscale_filter]
    if gs.upscale_sharpness:
        cmd += ["--sharpness", str(gs.upscale_sharpness)]
    if gs.hdr:
        cmd += ["--hdr-enabled"]
    if gs.frame_limit:
        cmd += ["-r", str(gs.frame_limit)]
    if gs.mangoapp:
        cmd += ["--mangoapp"]
    if gs.extra_args.strip():
        cmd += shlex.split(gs.extra_args)
    cmd += ["--"]
    return cmd


# Steam expects this to point to the Steam root for overlay / VR support.
# We set it to the canonical ~/.steam/root symlink; if absent, leave empty.
_STEAM_ROOT = Path.home() / ".steam" / "root"


class Launcher:
    """Tracks running apps and manages the launch/stop lifecycle."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._lock = threading.Lock()
        # app_id → Popen
        self._running: dict[str, subprocess.Popen] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_running(self, app_id: str) -> bool:
        with self._lock:
            return app_id in self._running

    def running_ids(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._running)

    def launch(
        self,
        app: AppEntry,
        runtime: Runtime,
        app_config: AppConfig,
        on_exit: Callable[[str], None] | None = None,
    ) -> None:
        """Launch *app* using *runtime*.  No-op if already running."""
        with self._lock:
            if app.app_id in self._running:
                return

        cmd = self.build_command(app, runtime, app_config)
        env = self.build_env(app, runtime, app_config)

        log_path = self._config.logs_dir / f"{app.app_id}.log"
        log_file = open(log_path, "w")  # noqa: SIM115 — kept open until process exits

        start_time = time.monotonic()
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,  # detach from our terminal
        )
        with self._lock:
            self._running[app.app_id] = proc

        # Watch for exit in a daemon thread; use GLib.idle_add to fire
        # the callback safely on the GTK main thread.
        threading.Thread(
            target=self._watch,
            args=(app.app_id, proc, log_file, on_exit, start_time),
            daemon=True,
        ).start()

    def stop(self, app_id: str) -> None:
        """Send SIGTERM to a running app.  The watch thread handles cleanup."""
        with self._lock:
            proc = self._running.get(app_id)
        if proc:
            proc.terminate()

    def build_command(self, app: AppEntry, runtime: Runtime, app_config: AppConfig) -> list[str]:
        """Build the launch command list for an app."""
        return self._build_command(app, runtime, app_config)

    def build_env(self, app: AppEntry, runtime: Runtime, app_config: AppConfig) -> dict[str, str]:
        """Build the environment dict for launching an app."""
        return self._build_env(app, runtime, app_config)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _watch(
        self,
        app_id: str,
        proc: subprocess.Popen,
        log_file,
        on_exit: Callable[[str], None] | None,
        start_time: float,
    ) -> None:
        try:
            proc.wait()
            elapsed = int(time.monotonic() - start_time)
        except Exception:
            elapsed = int(time.monotonic() - start_time)
            raise
        finally:
            log_file.close()
            # Guard against double-cleanup if stop() races with natural exit
            with self._lock:
                was_tracked = self._running.pop(app_id, None) is not None

        if not was_tracked:
            return

        from exwin.db.apps import update_playtime

        update_playtime(app_id, elapsed)
        if on_exit:
            GLib.idle_add(on_exit, app_id)

    def _build_command(self, app: AppEntry, runtime: Runtime, app_config: AppConfig) -> list[str]:
        if not app.install_path:
            raise FileNotFoundError("No install path set for this app.")
        exe_path = app.install_path / app.exe_path
        if not exe_path.exists():
            raise FileNotFoundError(
                f"Executable not found: {exe_path}\nCheck the executable path in app settings."
            )
        exe_full = str(exe_path)

        if runtime.is_proton:
            # Use waitforexitandrun so ProtonFixes' check_conditions() triggers
            # (it requires 'waitforexitandrun' in sys.argv[1]).  Plain `run`
            # bypasses game-specific fixes that many titles need to launch.
            cmd = [str(runtime.proton_binary), "waitforexitandrun", exe_full]
        else:
            cmd = [str(runtime.wine_binary), exe_full]

        cmd.extend(app_config.launch_args)

        # Optional wrappers — prepended in reverse order of precedence
        # Only add if the binary is available; silently skip if not installed.
        # When gamescope --mangoapp is active, suppress the outer mangohud
        # wrapper (it would double-render the HUD).
        gs = app_config.gamescope
        gs_active = gs.enabled and shutil.which("gamescope") is not None
        if app_config.mangohud and shutil.which("mangohud") and not (gs_active and gs.mangoapp):
            cmd = ["mangohud"] + cmd
        if app_config.gamemode and shutil.which("gamemoderun"):
            cmd = ["gamemoderun"] + cmd
        if gs_active:
            cmd = _build_gamescope_prefix(gs) + cmd

        return cmd

    def _build_env(self, app: AppEntry, runtime: Runtime, app_config: AppConfig) -> dict[str, str]:
        env = os.environ.copy()

        prefix_root = app.prefix_path

        if runtime.is_proton:
            env["STEAM_COMPAT_DATA_PATH"] = str(prefix_root)
            env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = (
                str(_STEAM_ROOT) if _STEAM_ROOT.exists() else ""
            )
            # ProtonFixes' get_game_id() reads SteamAppId / SteamGameId, then
            # falls back to digits in STEAM_COMPAT_DATA_PATH.  Our prefix paths
            # have no digits, so fall-back raises IndexError.  Setting 0 marks
            # this as a non-Steam game; ProtonFixes will find no fix to apply.
            env.setdefault("SteamAppId", "0")
            env.setdefault("SteamGameId", "0")
            # WINEPREFIX is managed by Proton (it uses pfx/ inside compat data)
        else:
            env["WINEPREFIX"] = str(prefix_root)

        env["WINEARCH"] = app_config.arch

        # DLL overrides
        if app_config.dll_overrides:
            overrides = ";".join(f"{dll}={mode}" for dll, mode in app_config.dll_overrides.items())
            existing = env.get("WINEDLLOVERRIDES", "")
            env["WINEDLLOVERRIDES"] = f"{existing};{overrides}" if existing else overrides

        # GPU selection via DRI_PRIME
        if app_config.gpu_index is not None:
            global _GPUS
            if _GPUS is None:
                _GPUS = detect_gpus()
            env["DRI_PRIME"] = str(app_config.gpu_index)
            if app_config.gpu_index < len(_GPUS):
                env.setdefault("DXVK_FILTER_DEVICE_NAME", _GPUS[app_config.gpu_index].name)

        # User-supplied extra env vars (applied last so they can override defaults)
        env.update(app_config.env)

        return env
