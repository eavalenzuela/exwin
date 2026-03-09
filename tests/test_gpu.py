"""Tests for exwin.backend.gpu."""

from __future__ import annotations

from unittest.mock import patch

from exwin.backend.gpu import GPU, _is_gpu_class, _parse_lspci

# ---------------------------------------------------------------------------
# _is_gpu_class
# ---------------------------------------------------------------------------


class TestIsGpuClass:
    def test_vga(self) -> None:
        assert _is_gpu_class("VGA compatible controller") is True

    def test_3d(self) -> None:
        assert _is_gpu_class("3D controller") is True

    def test_display(self) -> None:
        assert _is_gpu_class("Display controller") is True

    def test_non_gpu(self) -> None:
        assert _is_gpu_class("Audio device") is False

    def test_empty(self) -> None:
        assert _is_gpu_class("") is False


# ---------------------------------------------------------------------------
# _parse_lspci
# ---------------------------------------------------------------------------


class TestParseLspci:
    def test_parses_gpu_stanza(self) -> None:
        lspci_output = (
            "Slot:\t06:00.0\n"
            "Class:\tVGA compatible controller\n"
            "Vendor:\tAdvanced Micro Devices, Inc. [AMD/ATI]\n"
            "Device:\tNavi 32 [Radeon RX 7700S]\n"
            "\n"
            "Slot:\t00:1f.3\n"
            "Class:\tAudio device\n"
            "Vendor:\tIntel Corporation\n"
            "Device:\tAlder Lake PCH-P HD Audio\n"
            "\n"
        )
        with patch("exwin.backend.gpu.subprocess.run") as mock_run:
            mock_run.return_value.stdout = lspci_output
            result = _parse_lspci()

        assert "06:00.0" in result
        assert result["06:00.0"] == "Navi 32 [Radeon RX 7700S]"
        # Audio device should not be included
        assert "00:1f.3" not in result

    def test_handles_missing_lspci(self) -> None:
        with patch("exwin.backend.gpu.subprocess.run", side_effect=FileNotFoundError):
            assert _parse_lspci() == {}

    def test_handles_timeout(self) -> None:
        import subprocess

        with patch(
            "exwin.backend.gpu.subprocess.run", side_effect=subprocess.TimeoutExpired("lspci", 5)
        ):
            assert _parse_lspci() == {}

    def test_handles_last_stanza_without_trailing_blank(self) -> None:
        lspci_output = (
            "Slot:\t01:00.0\nClass:\t3D controller\nVendor:\tNVIDIA\nDevice:\tGeForce RTX 4090\n"
        )
        with patch("exwin.backend.gpu.subprocess.run") as mock_run:
            mock_run.return_value.stdout = lspci_output
            result = _parse_lspci()

        assert result["01:00.0"] == "GeForce RTX 4090"


# ---------------------------------------------------------------------------
# detect_gpus
# ---------------------------------------------------------------------------


class TestDetectGpus:
    def test_gpu_dataclass(self) -> None:
        gpu = GPU(index=0, name="AMD Radeon RX 7700S", vendor="amd")
        assert gpu.index == 0
        assert gpu.name == "AMD Radeon RX 7700S"
        assert gpu.vendor == "amd"

    def test_vendor_map(self) -> None:
        from exwin.backend.gpu import _VENDOR_MAP

        assert _VENDOR_MAP["0x1002"] == "amd"
        assert _VENDOR_MAP["0x10de"] == "nvidia"
        assert _VENDOR_MAP["0x8086"] == "intel"
