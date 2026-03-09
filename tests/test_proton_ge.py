"""Tests for exwin.backend.proton_ge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from exwin.backend.proton_ge import (
    download_and_install,
    find_ge_proton_asset,
    is_installed,
)

# ---------------------------------------------------------------------------
# find_ge_proton_asset
# ---------------------------------------------------------------------------


class TestFindGeProtonAsset:
    def test_finds_tar_gz(self) -> None:
        release = {
            "tag_name": "GE-Proton9-27",
            "assets": [
                {"name": "GE-Proton9-27.sha512sum"},
                {"name": "GE-Proton9-27.tar.gz", "browser_download_url": "https://..."},
            ],
        }
        asset = find_ge_proton_asset(release)
        assert asset["name"] == "GE-Proton9-27.tar.gz"

    def test_excludes_sha512sum(self) -> None:
        release = {
            "tag_name": "GE-Proton9-27",
            "assets": [
                {"name": "GE-Proton9-27.tar.gz.sha512sum"},
                {"name": "GE-Proton9-27.tar.gz", "browser_download_url": "https://..."},
            ],
        }
        asset = find_ge_proton_asset(release)
        assert not asset["name"].endswith(".sha512sum")

    def test_raises_when_no_tar_gz(self) -> None:
        release = {"tag_name": "v1", "assets": [{"name": "README.md"}]}
        with pytest.raises(RuntimeError, match="No .tar.gz asset"):
            find_ge_proton_asset(release)


# ---------------------------------------------------------------------------
# is_installed
# ---------------------------------------------------------------------------


class TestIsInstalled:
    def test_true_when_exists(self, tmp_path: Path) -> None:
        (tmp_path / "GE-Proton9-27").mkdir()
        assert is_installed("GE-Proton9-27", tmp_path) is True

    def test_false_when_missing(self, tmp_path: Path) -> None:
        assert is_installed("GE-Proton9-27", tmp_path) is False


# ---------------------------------------------------------------------------
# download_and_install
# ---------------------------------------------------------------------------


class TestDownloadAndInstall:
    def test_raises_if_already_installed(self, tmp_path: Path) -> None:
        (tmp_path / "GE-Proton9-27").mkdir()
        release = {
            "tag_name": "GE-Proton9-27",
            "assets": [
                {
                    "name": "GE-Proton9-27.tar.gz",
                    "browser_download_url": "https://...",
                    "size": 100,
                },
            ],
        }
        with pytest.raises(RuntimeError, match="already installed"):
            download_and_install(release, tmp_path)

    def test_progress_callback(self, tmp_path: Path) -> None:
        release = {
            "tag_name": "GE-Proton9-28",
            "assets": [
                {"name": "GE-Proton9-28.tar.gz", "browser_download_url": "https://dl", "size": 100},
            ],
        }

        progress_calls = []

        import io
        import tarfile

        # Create a valid tar.gz in memory
        tar_buf = io.BytesIO()
        with tarfile.open(fileobj=tar_buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(name="GE-Proton9-28/proton")
            info.size = 5
            tf.addfile(info, io.BytesIO(b"hello"))
        tar_data = tar_buf.getvalue()

        mock_resp = MagicMock()
        mock_resp.read.side_effect = [tar_data, b""]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("exwin.backend.proton_ge.urllib.request.urlopen", return_value=mock_resp):
            result = download_and_install(
                release, tmp_path, on_progress=lambda d, t: progress_calls.append((d, t))
            )

        assert len(progress_calls) > 0
        assert result.exists()
