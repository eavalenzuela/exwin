"""Tests for exwin.backend.auto_detect (auto-detection install route)."""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from exwin.backend.archive_installer import detect_sfx_archive
from exwin.backend.auto_detect import (
    analyze_installer,
    clean_title,
    detect_installer_tech,
    detect_pe_arch,
    find_archive_parts,
    pick_runtime,
)
from exwin.backend.gog_installer import InstallerInfo
from exwin.backend.runtime import Runtime
from exwin.models import RuntimeType

_RAR_MAGIC = b"Rar!\x1a\x07\x00"
_7Z_MAGIC = b"7z\xbc\xaf\x27\x1c"


def _write_pe(path: Path, machine: int = 0x014C, extra: bytes = b"") -> Path:
    """Write a minimal PE file with the given machine type."""
    e_lfanew = 0x80
    head = bytearray(e_lfanew + 24)
    head[0:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, e_lfanew)
    head[e_lfanew : e_lfanew + 4] = b"PE\x00\x00"
    struct.pack_into("<H", head, e_lfanew + 4, machine)
    path.write_bytes(bytes(head) + extra)
    return path


@pytest.fixture
def wine_rt() -> Runtime:
    return Runtime(name="Wine (wine-9.0)", type=RuntimeType.WINE, path=Path("/usr"))


@pytest.fixture
def proton_rt() -> Runtime:
    return Runtime(
        name="Proton 9.0", type=RuntimeType.PROTON, path=Path("/opt/p9"), version="proton-9.0-4"
    )


@pytest.fixture
def ge_rt() -> Runtime:
    return Runtime(
        name="GE-Proton9-5", type=RuntimeType.PROTON, path=Path("/opt/ge9"), version="GE-Proton9-5"
    )


# ---------------------------------------------------------------------------
# Low-level probes
# ---------------------------------------------------------------------------


class TestDetectPeArch:
    def test_win32(self, tmp_path: Path) -> None:
        assert detect_pe_arch(_write_pe(tmp_path / "a.exe", 0x014C)) == "win32"

    def test_win64(self, tmp_path: Path) -> None:
        assert detect_pe_arch(_write_pe(tmp_path / "a.exe", 0x8664)) == "win64"

    def test_not_pe(self, tmp_path: Path) -> None:
        f = tmp_path / "a.exe"
        f.write_bytes(b"hello world, definitely not an executable")
        assert detect_pe_arch(f) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        assert detect_pe_arch(tmp_path / "nope.exe") is None


class TestDetectInstallerTech:
    def test_nsis(self, tmp_path: Path) -> None:
        f = _write_pe(tmp_path / "a.exe", extra=b"...Nullsoft Install System v3.08...")
        assert detect_installer_tech(f) == "nsis"

    def test_innosetup(self, tmp_path: Path) -> None:
        f = _write_pe(tmp_path / "a.exe", extra=b"...Inno Setup Setup Data (5.5.7)...")
        assert detect_installer_tech(f) == "innosetup"

    def test_setup_factory(self, tmp_path: Path) -> None:
        f = _write_pe(tmp_path / "a.exe", extra=b"...Setup Factory 9.0...")
        assert detect_installer_tech(f) == "setup-factory"

    def test_unknown(self, tmp_path: Path) -> None:
        f = _write_pe(tmp_path / "a.exe", extra=b"nothing to see here")
        assert detect_installer_tech(f) == "unknown"


class TestDetectSfxArchive:
    def test_rar_sfx(self, tmp_path: Path) -> None:
        f = _write_pe(tmp_path / "a.exe", extra=b"stub" + _RAR_MAGIC + b"payload")
        assert detect_sfx_archive(f) == "rar"

    def test_7z_sfx(self, tmp_path: Path) -> None:
        f = _write_pe(tmp_path / "a.exe", extra=b"stub" + _7Z_MAGIC + b"payload")
        assert detect_sfx_archive(f) == "7z"

    def test_plain_pe(self, tmp_path: Path) -> None:
        f = _write_pe(tmp_path / "a.exe", extra=b"just a program")
        assert detect_sfx_archive(f) is None

    def test_not_mz(self, tmp_path: Path) -> None:
        f = tmp_path / "a.zip"
        f.write_bytes(b"PK\x03\x04" + _RAR_MAGIC)
        assert detect_sfx_archive(f) is None


class TestCleanTitle:
    def test_part_suffix(self) -> None:
        assert clean_title("Koihime Musou.part1") == "Koihime Musou"

    def test_setup_prefix_and_version(self) -> None:
        assert clean_title("setup_balrum_1.03") == "Balrum"

    def test_plain_name_untouched(self) -> None:
        assert clean_title("Stardew Valley") == "Stardew Valley"

    def test_never_empty(self) -> None:
        assert clean_title("part1") == "part1"


class TestFindArchiveParts:
    def test_winrar_part_naming(self, tmp_path: Path) -> None:
        first = tmp_path / "Game.part1.exe"
        first.touch()
        p2 = tmp_path / "Game.part2.rar"
        p2.touch()
        p3 = tmp_path / "Game.part3.rar"
        p3.touch()
        (tmp_path / "Other.part2.rar").touch()
        assert find_archive_parts(first) == [p2, p3]

    def test_r00_naming(self, tmp_path: Path) -> None:
        first = tmp_path / "Game.exe"
        first.touch()
        r00 = tmp_path / "Game.r00"
        r00.touch()
        r01 = tmp_path / "Game.r01"
        r01.touch()
        assert find_archive_parts(first) == [r00, r01]

    def test_single_file(self, tmp_path: Path) -> None:
        first = tmp_path / "Game.exe"
        first.touch()
        assert find_archive_parts(first) == []


class TestPickRuntime:
    def test_empty(self) -> None:
        idx, reason = pick_runtime([])
        assert idx is None
        assert reason

    def test_prefers_ge_proton(self, wine_rt, proton_rt, ge_rt) -> None:
        idx, reason = pick_runtime([wine_rt, proton_rt, ge_rt])
        assert idx == 2
        assert "GE-Proton9-5" in reason

    def test_prefers_newest_ge(self, ge_rt) -> None:
        old_ge = Runtime(
            name="GE-Proton8-32",
            type=RuntimeType.PROTON,
            path=Path("/opt/ge8"),
            version="GE-Proton8-32",
        )
        idx, _ = pick_runtime([old_ge, ge_rt])
        assert idx == 1

    def test_proton_over_wine(self, wine_rt, proton_rt) -> None:
        idx, _ = pick_runtime([wine_rt, proton_rt])
        assert idx == 1

    def test_wine_only(self, wine_rt) -> None:
        idx, reason = pick_runtime([wine_rt])
        assert idx == 0


# ---------------------------------------------------------------------------
# analyze_installer routing
# ---------------------------------------------------------------------------


class TestAnalyzeInstaller:
    def test_msi_routes_generic(self, tmp_path: Path, ge_rt) -> None:
        msi = tmp_path / "Setup Game.msi"
        msi.write_bytes(b"\xd0\xcf\x11\xe0")
        plan = analyze_installer(msi, [ge_rt])
        assert plan.route == "generic"
        assert plan.tech == "msi"
        assert plan.runtime_index == 0

    def test_zip_routes_archive(self, tmp_path: Path, ge_rt) -> None:
        zf = tmp_path / "My Game v2.zip"
        zf.write_bytes(b"PK\x03\x04" + b"\x00" * 32)
        plan = analyze_installer(zf, [ge_rt])
        assert plan.route == "archive"
        assert plan.archive_kind == "zip"
        assert not plan.blocked

    def test_multipart_rar_sfx_routes_archive(self, tmp_path: Path, ge_rt) -> None:
        sfx = _write_pe(tmp_path / "Koihime Musou.part1.exe", extra=b"stub" + _RAR_MAGIC)
        (tmp_path / "Koihime Musou.part2.rar").touch()
        with (
            patch("exwin.backend.auto_detect.find_innoextract", side_effect=RuntimeError),
            patch("exwin.backend.auto_detect.archive_tool_available", return_value=True),
        ):
            plan = analyze_installer(sfx, [ge_rt])
        assert plan.route == "archive"
        assert plan.tech == "rar-sfx"
        assert plan.archive_kind == "rar"
        assert plan.title == "Koihime Musou"
        assert len(plan.parts) == 1

    def test_sfx_blocked_without_tool(self, tmp_path: Path, ge_rt) -> None:
        sfx = _write_pe(tmp_path / "Game.part1.exe", extra=_RAR_MAGIC)
        (tmp_path / "Game.part2.rar").touch()
        with (
            patch("exwin.backend.auto_detect.find_innoextract", side_effect=RuntimeError),
            patch("exwin.backend.auto_detect.archive_tool_available", return_value=False),
        ):
            plan = analyze_installer(sfx, [ge_rt])
        assert plan.blocked
        assert plan.warnings

    def test_gog_innosetup_routes_gog(self, tmp_path: Path, ge_rt) -> None:
        exe = _write_pe(tmp_path / "setup_balrum_1.03.exe", extra=b"Inno Setup")
        info = InstallerInfo(title="Balrum", game_id="1436885438", setup_version="5.5.7")
        with (
            patch(
                "exwin.backend.auto_detect.find_innoextract", return_value="/usr/bin/innoextract"
            ),
            patch("exwin.backend.auto_detect.subprocess.run") as mock_run,
            patch("exwin.backend.auto_detect.probe", return_value=info),
        ):
            mock_run.return_value.returncode = 0
            plan = analyze_installer(exe, [ge_rt])
        assert plan.route == "gog"
        assert plan.tech == "innosetup-gog"
        assert plan.title == "Balrum"
        assert plan.game_id == "1436885438"

    def test_unknown_exe_routes_generic(self, tmp_path: Path, ge_rt) -> None:
        exe = _write_pe(tmp_path / "GameSetup.exe", extra=b"mystery")
        with (
            patch(
                "exwin.backend.auto_detect.find_innoextract", return_value="/usr/bin/innoextract"
            ),
            patch("exwin.backend.auto_detect.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 1
            plan = analyze_installer(exe, [ge_rt])
        assert plan.route == "generic"
        assert plan.tech == "unknown"

    def test_missing_innoextract_warns(self, tmp_path: Path, ge_rt) -> None:
        exe = _write_pe(tmp_path / "GameSetup.exe")
        with patch("exwin.backend.auto_detect.find_innoextract", side_effect=RuntimeError):
            plan = analyze_installer(exe, [ge_rt])
        assert plan.route == "generic"
        assert any("innoextract" in w for w in plan.warnings)

    def test_proton_disables_dxvk_install(self, tmp_path: Path, ge_rt) -> None:
        zf = tmp_path / "game.zip"
        zf.write_bytes(b"PK\x03\x04")
        plan = analyze_installer(zf, [ge_rt])
        assert plan.dxvk is False
        assert plan.vkd3d is False
        assert any("built in" in r for r in plan.reasons)

    def test_wine_with_vulkan_enables_dxvk(self, tmp_path: Path, wine_rt) -> None:
        zf = tmp_path / "game.zip"
        zf.write_bytes(b"PK\x03\x04")
        with patch("exwin.backend.auto_detect.vulkan_available", return_value=True):
            plan = analyze_installer(zf, [wine_rt])
        assert plan.dxvk is True

    def test_wine_without_vulkan_warns(self, tmp_path: Path, wine_rt) -> None:
        zf = tmp_path / "game.zip"
        zf.write_bytes(b"PK\x03\x04")
        with patch("exwin.backend.auto_detect.vulkan_available", return_value=False):
            plan = analyze_installer(zf, [wine_rt])
        assert plan.dxvk is False
        assert any("Vulkan" in w for w in plan.warnings)

    def test_no_runtimes(self, tmp_path: Path) -> None:
        zf = tmp_path / "game.zip"
        zf.write_bytes(b"PK\x03\x04")
        plan = analyze_installer(zf, [])
        assert plan.runtime_index is None
        assert plan.route == "archive"

    def test_labels(self, tmp_path: Path, ge_rt) -> None:
        zf = tmp_path / "game.zip"
        zf.write_bytes(b"PK\x03\x04")
        plan = analyze_installer(zf, [ge_rt])
        assert "ZIP" in plan.tech_label
        assert plan.route_label
