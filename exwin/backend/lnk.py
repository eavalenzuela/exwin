"""Minimal Windows ``.lnk`` (Shell Link) parser — resolve the target path.

GOG and other installers often leave ``.lnk`` stubs pointing at the real game
executable (frequently with the right arguments and working dir baked in).
This parses just enough of [MS-SHLLINK] to recover the target:

* ``LinkInfo`` → ``LocalBasePath`` (+ ``CommonPathSuffix``) — the absolute
  Windows path, preferred when present.
* ``RELATIVE_PATH`` StringData — fallback, resolved against the ``.lnk``'s
  own directory (useful because our extracted trees rarely live at the
  drive-letter paths the absolute form encodes).

No COM, no shell — pure struct parsing, safe on arbitrary input: any
malformed file simply yields ``None``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

_HEADER_SIZE = 0x4C
_LINK_CLSID = bytes.fromhex("0114020000000000c000000000000046")

# LinkFlags bits (MS-SHLLINK §2.1.1)
_HAS_LINK_TARGET_ID_LIST = 0x01
_HAS_LINK_INFO = 0x02
_HAS_NAME = 0x04
_HAS_RELATIVE_PATH = 0x08
_IS_UNICODE = 0x80

# LinkInfoFlags bits (§2.3)
_VOLUME_ID_AND_LOCAL_BASE_PATH = 0x01


def parse_lnk(path: Path) -> LnkTarget | None:
    """Parse *path* as a Shell Link; return the target info or ``None``.

    ``None`` means "not a valid .lnk" or "no usable target field" — callers
    should treat both the same way (skip the stub).
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < _HEADER_SIZE:
        return None
    (header_size,) = struct.unpack_from("<I", data, 0)
    if header_size != _HEADER_SIZE or data[4:20] != _LINK_CLSID:
        return None
    (flags,) = struct.unpack_from("<I", data, 20)

    offset = _HEADER_SIZE
    try:
        if flags & _HAS_LINK_TARGET_ID_LIST:
            (idlist_size,) = struct.unpack_from("<H", data, offset)
            offset += 2 + idlist_size

        local_base = ""
        if flags & _HAS_LINK_INFO:
            li_start = offset
            li_size, _li_header_size, li_flags, _vol_off, base_off, _cnrl_off, suffix_off = (
                struct.unpack_from("<7I", data, li_start)
            )
            if li_flags & _VOLUME_ID_AND_LOCAL_BASE_PATH:
                base = _read_cstr(data, li_start + base_off)
                suffix = _read_cstr(data, li_start + suffix_off)
                local_base = base + suffix
            offset = li_start + li_size

        # StringData section: length-prefixed strings in LinkFlags order.
        unicode = bool(flags & _IS_UNICODE)
        if flags & _HAS_NAME:
            _, offset = _read_string_data(data, offset, unicode)
        relative = ""
        if flags & _HAS_RELATIVE_PATH:
            relative, offset = _read_string_data(data, offset, unicode)
    except (struct.error, IndexError, ValueError):
        # struct: short buffer; ValueError: unterminated string (data.index)
        return None

    if not local_base and not relative:
        return None
    return LnkTarget(local_base_path=local_base, relative_path=relative)


@dataclass
class LnkTarget:
    """Resolved target fields of a parsed ``.lnk``."""

    local_base_path: str = ""  # absolute Windows path, e.g. C:\Games\x.exe
    relative_path: str = ""  # e.g. ..\..\Games\x.exe (relative to the .lnk)

    def resolve_in(self, lnk_path: Path) -> Path | None:
        """Best-effort filesystem resolution of the target near *lnk_path*.

        Tries the RELATIVE_PATH against the ``.lnk``'s directory first (our
        extracted trees rarely match the encoded drive-letter path), then
        falls back to matching the LocalBasePath's basename in that directory.
        Returns ``None`` if nothing exists on disk.
        """
        base_dir = lnk_path.parent
        if self.relative_path:
            candidate = base_dir / self.relative_path.replace("\\", "/")
            try:
                candidate = candidate.resolve()
            except OSError:
                candidate = None
            if candidate is not None and candidate.is_file():
                return candidate
        if self.local_base_path:
            name = self.local_base_path.replace("\\", "/").rsplit("/", 1)[-1]
            candidate = base_dir / name
            if candidate.is_file():
                try:
                    return candidate.resolve()
                except OSError:
                    return candidate
        return None


def resolve_lnk_targets(root: Path) -> list[Path]:
    """Resolve every ``.lnk`` under *root* to an existing ``.exe``, deduplicated.

    Only targets that resolve to a real file inside *root* are returned —
    a stub pointing at ``C:\\Windows\\notepad.exe`` is of no use to us.
    """
    results: list[Path] = []
    seen: set[Path] = set()
    if not root.is_dir():
        return results
    for lnk in sorted(root.rglob("*.lnk")):
        target = parse_lnk(lnk)
        if target is None:
            continue
        resolved = target.resolve_in(lnk)
        if resolved is None or resolved.suffix.lower() != ".exe":
            continue
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue  # points outside the import tree
        if resolved not in seen:
            seen.add(resolved)
            results.append(resolved)
    return results


def _read_cstr(data: bytes, offset: int) -> str:
    """Read a NUL-terminated ANSI string at *offset* (system codepage ≈ cp1252)."""
    end = data.index(b"\x00", offset)
    return data[offset:end].decode("cp1252", errors="replace")


def _read_string_data(data: bytes, offset: int, unicode: bool) -> tuple[str, int]:
    """Read one StringData entry: uint16 char count, then the characters."""
    (count,) = struct.unpack_from("<H", data, offset)
    offset += 2
    if unicode:
        raw = data[offset : offset + count * 2]
        text = raw.decode("utf-16-le", errors="replace")
        offset += count * 2
    else:
        raw = data[offset : offset + count]
        text = raw.decode("cp1252", errors="replace")
        offset += count
    return text, offset
