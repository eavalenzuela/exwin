"""Tests for exwin.backend.install_worker."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from exwin.backend.config import Config
from exwin.backend.runtime import Runtime
from exwin.models import AppEntry, AppSource, RuntimeType


@pytest.fixture
def proton_rt(db: Config) -> Runtime:
    from exwin.db.runtimes import upsert_runtime

    rt = Runtime(name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"), version="9.0")
    db_id = upsert_runtime(rt)
    return Runtime(name=rt.name, type=rt.type, path=rt.path, version=rt.version, db_id=db_id)


@pytest.fixture
def gog_installer(tmp_path: Path) -> Path:
    exe = tmp_path / "setup_test_game.exe"
    exe.write_bytes(b"fake installer")
    return exe


@pytest.fixture
def mock_innoextract():
    """Patch innoextract calls used throughout the install pipeline."""
    with (
        patch("exwin.backend.gog_installer.find_innoextract", return_value="/usr/bin/innoextract"),
        patch("exwin.backend.gog_installer.subprocess.run") as mock_run,
        patch("exwin.backend.gog_installer.subprocess.Popen") as mock_popen,
    ):
        # probe() subprocess.run
        mock_run.return_value.stdout = (
            'Inspecting "Test Game"\n'
            "setup data version 5.6.2\n"
            "GOG.com game ID is 1234567890\n"
            " - en-US\n"
        )
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0

        # extract() subprocess.Popen
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["Extracting file1.txt\n", "Extracting file2.exe\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        yield mock_run, mock_popen


class TestInstallGog:
    def test_full_pipeline(
        self,
        gog_installer: Path,
        proton_rt: Runtime,
        mock_innoextract,
        db: Config,
    ) -> None:
        from exwin.backend.install_worker import install_gog

        # Set up expected game files after extraction
        def fake_extract(installer_path, output_dir, **kwargs):
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "Game.exe").touch()
            info = {
                "gameId": "1234567890",
                "name": "Test Game",
                "playTasks": [{"isPrimary": True, "type": "FileTask", "path": "Game.exe"}],
            }
            (output_dir / "goggame-1234567890.info").write_text(json.dumps(info))

        with (
            patch("exwin.backend.install_worker.extract", side_effect=fake_extract),
            patch("exwin.backend.install_worker.count_files", return_value=2),
            patch(
                "exwin.backend.install_worker.create_prefix",
                return_value=db.prefixes_dir / "gog-1234567890",
            ),
            patch("exwin.backend.install_worker.validate_checksums"),
            patch("exwin.backend.install_worker.apply_metadata"),
        ):
            app = install_gog(
                installer_path=gog_installer,
                config=db,
                runtime=proton_rt,
            )

        assert app.app_id == "gog-1234567890"
        assert app.name == "Test Game"
        assert app.source == AppSource.GOG
        assert app.exe_path == "Game.exe"

    def test_raises_if_already_installed(
        self,
        db: Config,
        gog_installer: Path,
        proton_rt: Runtime,
        mock_innoextract,
    ) -> None:
        from exwin.backend.install_worker import install_gog

        # Pre-create the install dir
        install_dir = db.installs_dir / "gog-1234567890"
        install_dir.mkdir(parents=True)

        with pytest.raises(RuntimeError, match="already installed"):
            with (
                patch("exwin.backend.install_worker.validate_checksums"),
            ):
                install_gog(
                    installer_path=gog_installer,
                    config=db,
                    runtime=proton_rt,
                )


class TestInstallGogDlc:
    def test_extracts_into_base_game(
        self,
        db: Config,
        gog_installer: Path,
        proton_rt: Runtime,
        mock_innoextract,
    ) -> None:
        from exwin.backend.install_worker import install_gog_dlc

        base_install = db.installs_dir / "base-game"
        base_install.mkdir(parents=True)
        base_app = AppEntry(
            app_id="base-game",
            name="Base Game",
            source=AppSource.GOG,
            install_path=base_install,
            prefix_path=db.prefixes_dir / "base-game",
        )

        extracted_files = []

        def fake_extract(installer_path, output_dir, **kwargs):
            extracted_files.append(str(output_dir))
            (output_dir / "dlc_file.txt").touch()

        with patch("exwin.backend.install_worker.extract", side_effect=fake_extract):
            title = install_gog_dlc(
                installer_path=gog_installer,
                base_app=base_app,
                config=db,
                runtime=proton_rt,
            )

        assert title == "Test Game"
        assert str(base_install) in extracted_files
