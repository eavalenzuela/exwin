"""Tests for exwin.backend.runtime."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from exwin.backend.runtime import (
    Runtime,
    _read_proton_version,
    _read_wine_version,
    scan_runtimes,
)
from exwin.models import RuntimeType

# ---------------------------------------------------------------------------
# Runtime dataclass
# ---------------------------------------------------------------------------


class TestRuntime:
    def test_is_proton(self) -> None:
        rt = Runtime(name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"))
        assert rt.is_proton is True

    def test_is_not_proton(self) -> None:
        rt = Runtime(name="Wine", type=RuntimeType.WINE, path=Path("/usr"))
        assert rt.is_proton is False

    def test_proton_binary(self) -> None:
        rt = Runtime(name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"))
        assert rt.proton_binary == Path("/opt/proton/proton")

    def test_wine_binary_for_proton_falls_back_to_wine(self) -> None:
        # /opt/proton doesn't exist, so wine64 isn't found → falls back to wine
        rt = Runtime(name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"))
        assert rt.wine_binary == Path("/opt/proton/files/bin/wine")

    def test_wine_binary_for_proton_prefers_wine64(self, tmp_path: Path) -> None:
        # When wine64 exists alongside wine, prefer wine64 — the 32-bit wine
        # binary breaks under sandboxed runtimes that lack /lib/ld-linux.so.2.
        bindir = tmp_path / "files" / "bin"
        bindir.mkdir(parents=True)
        (bindir / "wine").touch()
        (bindir / "wine64").touch()
        rt = Runtime(name="Proton 10", type=RuntimeType.PROTON, path=tmp_path)
        assert rt.wine_binary == bindir / "wine64"

    def test_wine_binary_for_wine(self) -> None:
        rt = Runtime(name="Wine", type=RuntimeType.WINE, path=Path("/usr"))
        assert rt.wine_binary == Path("/usr/bin/wine")

    def test_str(self) -> None:
        rt = Runtime(name="GE-Proton9-27", type=RuntimeType.PROTON, path=Path("/p"))
        assert str(rt) == "GE-Proton9-27"


# ---------------------------------------------------------------------------
# _read_proton_version
# ---------------------------------------------------------------------------


class TestReadProtonVersion:
    def test_reads_version_file(self, tmp_path: Path) -> None:
        (tmp_path / "version").write_text("1769167055 proton-10.0-4\n")
        assert _read_proton_version(tmp_path) == "proton-10.0-4"

    def test_single_word_version(self, tmp_path: Path) -> None:
        (tmp_path / "version").write_text("GE-Proton9-27\n")
        assert _read_proton_version(tmp_path) == "GE-Proton9-27"

    def test_falls_back_to_dir_name(self, tmp_path: Path) -> None:
        proton_dir = tmp_path / "GE-Proton9-27"
        proton_dir.mkdir()
        assert _read_proton_version(proton_dir) == "GE-Proton9-27"


# ---------------------------------------------------------------------------
# _read_wine_version
# ---------------------------------------------------------------------------


class TestReadWineVersion:
    def test_returns_version_from_subprocess(self) -> None:
        with patch("exwin.backend.runtime.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "wine-9.0\n"
            assert _read_wine_version("/usr/bin/wine") == "wine-9.0"

    def test_returns_unknown_on_error(self) -> None:
        with patch("exwin.backend.runtime.subprocess.run", side_effect=OSError):
            assert _read_wine_version("/usr/bin/wine") == "unknown"


# ---------------------------------------------------------------------------
# scan_runtimes
# ---------------------------------------------------------------------------


class TestScanRuntimes:
    def test_finds_proton_dirs(self, tmp_path: Path) -> None:
        proton_dir = tmp_path / "GE-Proton9-27"
        proton_dir.mkdir()
        (proton_dir / "proton").touch()
        (proton_dir / "version").write_text("1234 GE-Proton9-27")

        with patch("exwin.backend.runtime._PROTON_SCAN_ROOTS", [tmp_path]):
            with patch("exwin.backend.runtime.shutil.which", return_value=None):
                runtimes = scan_runtimes()

        assert len(runtimes) == 1
        assert runtimes[0].name == "GE-Proton9-27"
        assert runtimes[0].type == RuntimeType.PROTON
        assert runtimes[0].version == "GE-Proton9-27"

    def test_skips_non_proton_dirs(self, tmp_path: Path) -> None:
        not_proton = tmp_path / "SomeDir"
        not_proton.mkdir()
        # No 'proton' binary inside

        with patch("exwin.backend.runtime._PROTON_SCAN_ROOTS", [tmp_path]):
            with patch("exwin.backend.runtime.shutil.which", return_value=None):
                runtimes = scan_runtimes()

        assert runtimes == []

    def test_finds_system_wine(self, tmp_path: Path) -> None:
        wine_bin = tmp_path / "bin" / "wine"
        wine_bin.parent.mkdir(parents=True)
        wine_bin.touch()

        with patch("exwin.backend.runtime._PROTON_SCAN_ROOTS", []):
            with patch("exwin.backend.runtime.shutil.which", return_value=str(wine_bin)):
                with patch("exwin.backend.runtime._read_wine_version", return_value="wine-9.0"):
                    runtimes = scan_runtimes()

        assert len(runtimes) == 1
        assert runtimes[0].type == RuntimeType.WINE
        assert runtimes[0].version == "wine-9.0"

    def test_deduplicates_by_resolved_path(self, tmp_path: Path) -> None:
        proton_dir = tmp_path / "proton1"
        proton_dir.mkdir()
        (proton_dir / "proton").touch()

        # Create a symlink to the same directory
        link = tmp_path / "proton_link"
        link.symlink_to(proton_dir)

        with patch("exwin.backend.runtime._PROTON_SCAN_ROOTS", [tmp_path]):
            with patch("exwin.backend.runtime.shutil.which", return_value=None):
                runtimes = scan_runtimes()

        # Both entries point to the same resolved path; should only appear once
        assert len(runtimes) == 1
