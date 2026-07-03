"""Tests for exwin.backend.lnk — minimal Shell Link (.lnk) parsing."""

from __future__ import annotations

import struct
from pathlib import Path

from exwin.backend.lnk import LnkTarget, parse_lnk, resolve_lnk_targets

_CLSID = bytes.fromhex("0114020000000000c000000000000046")

# LinkFlags bits mirrored from the module under test
_HAS_LINK_INFO = 0x02
_HAS_RELATIVE_PATH = 0x08
_IS_UNICODE = 0x80


def _make_lnk(local_base: str = "", relative: str = "", unicode: bool = True) -> bytes:
    """Craft a minimal, spec-shaped .lnk blob with the given target fields."""
    flags = 0
    body = b""

    if local_base:
        flags |= _HAS_LINK_INFO
        base_b = local_base.encode("cp1252") + b"\x00"
        suffix_b = b"\x00"  # empty CommonPathSuffix
        li_header = 28  # 7 uint32 fields
        base_off = li_header
        suffix_off = base_off + len(base_b)
        li_size = suffix_off + len(suffix_b)
        body += struct.pack("<7I", li_size, li_header, 0x1, 0, base_off, 0, suffix_off)
        body += base_b + suffix_b

    if relative:
        flags |= _HAS_RELATIVE_PATH
        if unicode:
            flags |= _IS_UNICODE
            body += struct.pack("<H", len(relative)) + relative.encode("utf-16-le")
        else:
            body += struct.pack("<H", len(relative)) + relative.encode("cp1252")

    header = struct.pack("<I", 0x4C) + _CLSID + struct.pack("<I", flags)
    header += b"\x00" * (0x4C - len(header))
    return header + body


class TestParseLnk:
    def test_local_base_path(self, tmp_path: Path) -> None:
        lnk = tmp_path / "game.lnk"
        lnk.write_bytes(_make_lnk(local_base="C:\\Games\\Witcher\\game.exe"))
        target = parse_lnk(lnk)
        assert target is not None
        assert target.local_base_path == "C:\\Games\\Witcher\\game.exe"

    def test_relative_path_unicode(self, tmp_path: Path) -> None:
        lnk = tmp_path / "game.lnk"
        lnk.write_bytes(_make_lnk(relative=".\\bin\\game.exe"))
        target = parse_lnk(lnk)
        assert target is not None
        assert target.relative_path == ".\\bin\\game.exe"

    def test_relative_path_ansi(self, tmp_path: Path) -> None:
        lnk = tmp_path / "game.lnk"
        lnk.write_bytes(_make_lnk(relative=".\\game.exe", unicode=False))
        target = parse_lnk(lnk)
        assert target is not None
        assert target.relative_path == ".\\game.exe"

    def test_both_fields(self, tmp_path: Path) -> None:
        lnk = tmp_path / "game.lnk"
        lnk.write_bytes(_make_lnk(local_base="C:\\g\\a.exe", relative="..\\a.exe"))
        target = parse_lnk(lnk)
        assert target is not None
        assert target.local_base_path == "C:\\g\\a.exe"
        assert target.relative_path == "..\\a.exe"

    def test_not_a_lnk_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "fake.lnk"
        f.write_bytes(b"MZ this is not a shell link at all")
        assert parse_lnk(f) is None

    def test_short_file_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "short.lnk"
        f.write_bytes(b"\x4c\x00\x00\x00")
        assert parse_lnk(f) is None

    def test_wrong_clsid_returns_none(self, tmp_path: Path) -> None:
        data = bytearray(_make_lnk(local_base="C:\\x.exe"))
        data[4] ^= 0xFF
        f = tmp_path / "bad.lnk"
        f.write_bytes(bytes(data))
        assert parse_lnk(f) is None

    def test_truncated_body_returns_none(self, tmp_path: Path) -> None:
        data = _make_lnk(local_base="C:\\Games\\long\\path\\game.exe")
        f = tmp_path / "trunc.lnk"
        f.write_bytes(data[: 0x4C + 4])  # header + a sliver of LinkInfo
        assert parse_lnk(f) is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert parse_lnk(tmp_path / "no-such.lnk") is None

    def test_no_target_fields_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.lnk"
        f.write_bytes(_make_lnk())
        assert parse_lnk(f) is None


class TestResolveIn:
    def test_relative_path_resolves(self, tmp_path: Path) -> None:
        (tmp_path / "bin").mkdir()
        exe = tmp_path / "bin" / "game.exe"
        exe.write_bytes(b"MZ")
        target = LnkTarget(relative_path=".\\bin\\game.exe")
        resolved = target.resolve_in(tmp_path / "Play.lnk")
        assert resolved == exe.resolve()

    def test_local_base_falls_back_to_basename(self, tmp_path: Path) -> None:
        exe = tmp_path / "game.exe"
        exe.write_bytes(b"MZ")
        target = LnkTarget(local_base_path="C:\\Program Files\\Game\\game.exe")
        resolved = target.resolve_in(tmp_path / "Play.lnk")
        assert resolved == exe.resolve()

    def test_nothing_on_disk_returns_none(self, tmp_path: Path) -> None:
        target = LnkTarget(local_base_path="C:\\gone.exe", relative_path=".\\gone.exe")
        assert target.resolve_in(tmp_path / "Play.lnk") is None


class TestResolveLnkTargets:
    def test_finds_exe_target(self, tmp_path: Path) -> None:
        exe = tmp_path / "game.exe"
        exe.write_bytes(b"MZ")
        (tmp_path / "Play Game.lnk").write_bytes(_make_lnk(relative=".\\game.exe"))
        assert resolve_lnk_targets(tmp_path) == [exe.resolve()]

    def test_deduplicates_targets(self, tmp_path: Path) -> None:
        exe = tmp_path / "game.exe"
        exe.write_bytes(b"MZ")
        (tmp_path / "a.lnk").write_bytes(_make_lnk(relative=".\\game.exe"))
        (tmp_path / "b.lnk").write_bytes(_make_lnk(relative=".\\game.exe"))
        assert resolve_lnk_targets(tmp_path) == [exe.resolve()]

    def test_skips_target_outside_root(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.exe"
        outside.write_bytes(b"MZ")
        root = tmp_path / "root"
        root.mkdir()
        (root / "escape.lnk").write_bytes(_make_lnk(relative="..\\outside.exe"))
        assert resolve_lnk_targets(root) == []

    def test_skips_non_exe_target(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("hi")
        (tmp_path / "doc.lnk").write_bytes(_make_lnk(relative=".\\readme.txt"))
        assert resolve_lnk_targets(tmp_path) == []

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        assert resolve_lnk_targets(tmp_path / "nope") == []
