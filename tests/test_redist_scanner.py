"""Tests for exwin.backend.redist_scanner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from exwin.backend.redist_scanner import RedistFinding, apply_finding, scan
from exwin.backend.runtime import Runtime
from exwin.models import RuntimeType

# ---------------------------------------------------------------------------
# scan()
# ---------------------------------------------------------------------------


class TestScan:
    def test_detects_vcredist_x64(self, tmp_path: Path) -> None:
        redist = tmp_path / "_CommonRedist" / "vcredist"
        redist.mkdir(parents=True)
        (redist / "vc_redist.x64.exe").touch()

        findings = scan(tmp_path)
        assert len(findings) == 1
        assert findings[0].kind == "vcredist-2015-2019-x64"
        assert findings[0].action == "verb"
        assert findings[0].payload == "vcrun2019"

    def test_detects_vcredist_x86(self, tmp_path: Path) -> None:
        (tmp_path / "vc_redist.x86.exe").touch()
        findings = scan(tmp_path)
        assert len(findings) == 1
        assert findings[0].kind == "vcredist-2015-2019-x86"

    def test_detects_ue_prereq(self, tmp_path: Path) -> None:
        d = tmp_path / "Engine" / "Extras" / "Redist"
        d.mkdir(parents=True)
        (d / "UE4PrereqSetup_x64.exe").touch()
        findings = scan(tmp_path)
        assert len(findings) == 1
        assert findings[0].kind == "ue-prereq-x64"
        assert findings[0].action == "run"

    def test_detects_dxsetup(self, tmp_path: Path) -> None:
        d = tmp_path / "DirectX"
        d.mkdir()
        (d / "DXSETUP.exe").touch()
        findings = scan(tmp_path)
        assert [f.kind for f in findings] == ["dxsetup"]

    def test_detects_multiple_distinct_kinds(self, tmp_path: Path) -> None:
        (tmp_path / "vc_redist.x64.exe").touch()
        (tmp_path / "oalinst.exe").touch()
        (tmp_path / "DXSETUP.exe").touch()
        findings = scan(tmp_path)
        kinds = {f.kind for f in findings}
        assert kinds == {"vcredist-2015-2019-x64", "openal", "dxsetup"}

    def test_deduplicates_same_kind(self, tmp_path: Path) -> None:
        (tmp_path / "a" / "vc_redist.x64.exe").parent.mkdir()
        (tmp_path / "a" / "vc_redist.x64.exe").touch()
        (tmp_path / "b" / "vc_redist.x64.exe").parent.mkdir()
        (tmp_path / "b" / "vc_redist.x64.exe").touch()
        findings = scan(tmp_path)
        assert len(findings) == 1

    def test_skips_uninstall_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "uninstall").mkdir()
        (tmp_path / "uninstall" / "vc_redist.x64.exe").touch()
        findings = scan(tmp_path)
        assert findings == []

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        assert scan(tmp_path / "nope") == []

    def test_returns_empty_for_clean_game(self, tmp_path: Path) -> None:
        (tmp_path / "Game.exe").touch()
        (tmp_path / "data.pak").touch()
        assert scan(tmp_path) == []

    def test_ignores_non_matching_exes(self, tmp_path: Path) -> None:
        (tmp_path / "GameLauncher.exe").touch()
        (tmp_path / "setup.exe").touch()  # "setup" alone is too vague
        assert scan(tmp_path) == []


# ---------------------------------------------------------------------------
# apply_finding()
# ---------------------------------------------------------------------------


@pytest.fixture
def wine_rt() -> Runtime:
    return Runtime(name="Wine", type=RuntimeType.WINE, path=Path("/usr"), version="9.0")


@pytest.fixture
def proton_rt() -> Runtime:
    return Runtime(
        name="Proton", type=RuntimeType.PROTON, path=Path("/opt/steam/proton"), version="9.0"
    )


class TestApplyFinding:
    def test_verb_calls_run_verbs(self, tmp_path: Path, wine_rt: Runtime) -> None:
        finding = RedistFinding(
            path=tmp_path / "vcredist.exe",
            kind="vcredist-2015-2019-x64",
            description="VC++ 2015-2019 x64",
            action="verb",
            payload="vcrun2019",
        )
        proc = MagicMock()
        proc.wait.return_value = 0
        with patch("exwin.backend.redist_scanner.run_verbs", return_value=proc) as mock_run:
            rc = apply_finding(finding, tmp_path / "prefix", wine_rt)
        mock_run.assert_called_once_with(tmp_path / "prefix", ["vcrun2019"], wine_rt)
        assert rc == 0

    def test_run_builds_wine_cmd(self, tmp_path: Path, wine_rt: Runtime) -> None:
        finding = RedistFinding(
            path=tmp_path / "UE4PrereqSetup_x64.exe",
            kind="ue-prereq-x64",
            description="UE4 Prereq",
            action="run",
            payload="/quiet /norestart",
        )
        proc = MagicMock()
        proc.stdout = iter([])
        proc.wait.return_value = 0
        with patch(
            "exwin.backend.redist_scanner.subprocess.Popen", return_value=proc
        ) as mock_popen:
            rc = apply_finding(finding, tmp_path / "prefix", wine_rt)
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == str(wine_rt.path / "bin" / "wine")
        assert cmd[1] == str(finding.path)
        assert cmd[2:] == ["/quiet", "/norestart"]
        env = mock_popen.call_args.kwargs["env"]
        assert env["WINEPREFIX"] == str(tmp_path / "prefix")
        assert rc == 0

    def test_run_builds_proton_cmd(self, tmp_path: Path, proton_rt: Runtime) -> None:
        finding = RedistFinding(
            path=tmp_path / "dxsetup.exe",
            kind="dxsetup",
            description="DX",
            action="run",
            payload="/silent",
        )
        proc = MagicMock()
        proc.stdout = iter([])
        proc.wait.return_value = 0
        with patch(
            "exwin.backend.redist_scanner.subprocess.Popen", return_value=proc
        ) as mock_popen:
            apply_finding(finding, tmp_path / "prefix", proton_rt)
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == str(proton_rt.path / "proton")
        assert cmd[1] == "run"
        env = mock_popen.call_args.kwargs["env"]
        assert env["STEAM_COMPAT_DATA_PATH"] == str(tmp_path / "prefix")

    def test_unknown_action_raises(self, tmp_path: Path, wine_rt: Runtime) -> None:
        finding = RedistFinding(
            path=tmp_path / "x.exe",
            kind="x",
            description="x",
            action="bogus",
            payload="",
        )
        with pytest.raises(ValueError, match="Unknown finding action"):
            apply_finding(finding, tmp_path / "prefix", wine_rt)
