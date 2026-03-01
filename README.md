# exwin

Offline-first Windows software/game manager for Linux — "offline Steam" with a Proton/Wine backend and first-class GOG offline installer automation.

## Features

- **GOG installer automation** — probe, extract, and install GOG offline installers (single-part and multi-part RAR/InnoSetup layouts) with automatic executable detection
- **DLC installs** — install GOG DLC on top of an existing base-game prefix
- **Library management** — searchable grid view with cover art; per-game settings persisted to `~/.local/share/exwin/`
- **Proton & Wine support** — launch games via any Proton (including Proton-GE) or Wine runtime detected under `~/.steam/root/`
- **Proton-GE installer** — fetch and install the latest Proton-GE release from within the app
- **DXVK / VKD3D-Proton** — one-click install via winetricks or bundled setup scripts
- **GPU selection** — per-game GPU override via `DRI_PRIME` / `DXVK_FILTER_DEVICE_NAME` on multi-GPU systems
- **Custom cover art** — set cover art from a local image file or an image URL in per-game settings
- **GOG metadata fetch** — pull title, description, and cover art from the GOG products API
- **Generic installer support** — run any Windows installer interactively via Wine, then select the resulting executable
- **Per-game configuration** — architecture (win32/win64), DXVK, VKD3D, winetricks verbs, gamemode, MangoHud, launch arguments, environment variables, DLL overrides, GPU override

## Requirements

- Python 3.11+, PyGObject, libadwaita 1.3+
- `innoextract` (≥ 1.9) — GOG/InnoSetup extraction; place at `~/.local/bin/innoextract` or on `$PATH`
- `unar` (apt: `universe`) — GOG multi-part RAR `.bin` extraction
- `winetricks` — optional, for DXVK/VKD3D and verb automation
- Proton or Wine runtime installed and discoverable under `~/.steam/root/`

## Installation / Running

```bash
python -m venv --system-site-packages .venv   # system-site-packages needed for PyGObject
.venv/bin/pip install -e .
.venv/bin/python -m exwin
```

## Data layout

```
~/.local/share/exwin/
├── library.db          # SQLite app registry
├── config.toml         # global config (data_dir, default runtime, etc.)
├── prefixes/<id>/      # Wine/Proton prefix roots
├── apps/<id>/          # install dirs + app.toml per-game config
├── metadata/<id>/      # cover art cache
├── runtimes/           # downloaded runtimes (Proton-GE, etc.)
└── logs/
```
