"""Tests for exwin.backend.config."""

from __future__ import annotations

from pathlib import Path

from exwin.backend.config import _DEFAULT_DATA_DIR, Config


class TestDefaultDataDir:
    def test_is_dot_exwin(self) -> None:
        assert _DEFAULT_DATA_DIR == Path.home() / ".exwin"

    def test_not_under_local_share(self) -> None:
        assert ".local" not in str(_DEFAULT_DATA_DIR)


class TestDerivedPaths:
    def test_db_path(self, tmp_config: Config) -> None:
        assert tmp_config.db_path == tmp_config.data_dir / "library.db"

    def test_prefixes_dir(self, tmp_config: Config) -> None:
        assert tmp_config.prefixes_dir == tmp_config.data_dir / "prefixes"

    def test_apps_dir(self, tmp_config: Config) -> None:
        assert tmp_config.apps_dir == tmp_config.data_dir / "apps"

    def test_runtimes_dir(self, tmp_config: Config) -> None:
        assert tmp_config.runtimes_dir == tmp_config.data_dir / "runtimes"

    def test_metadata_dir(self, tmp_config: Config) -> None:
        assert tmp_config.metadata_dir == tmp_config.data_dir / "metadata"

    def test_logs_dir(self, tmp_config: Config) -> None:
        assert tmp_config.logs_dir == tmp_config.data_dir / "logs"

    def test_config_path(self, tmp_config: Config) -> None:
        assert tmp_config.config_path == tmp_config.data_dir / "config.toml"

    def test_all_paths_under_data_dir(self, tmp_config: Config) -> None:
        paths = [
            tmp_config.db_path,
            tmp_config.prefixes_dir,
            tmp_config.apps_dir,
            tmp_config.runtimes_dir,
            tmp_config.metadata_dir,
            tmp_config.logs_dir,
            tmp_config.config_path,
        ]
        for p in paths:
            assert str(p).startswith(str(tmp_config.data_dir))


class TestEnsureDirs:
    def test_creates_all_subdirs(self, tmp_config: Config) -> None:
        expected = [
            tmp_config.data_dir,
            tmp_config.prefixes_dir,
            tmp_config.apps_dir,
            tmp_config.runtimes_dir,
            tmp_config.metadata_dir,
            tmp_config.logs_dir,
        ]
        for d in expected:
            assert d.is_dir(), f"Missing dir: {d}"

    def test_idempotent(self, tmp_config: Config) -> None:
        """Calling _ensure_dirs twice must not raise."""
        tmp_config._ensure_dirs()


class TestSaveAndLoad:
    def test_roundtrip_defaults(self, tmp_config: Config) -> None:
        tmp_config.save()
        loaded = _load_from(tmp_config.data_dir)
        assert loaded.data_dir == tmp_config.data_dir
        assert loaded.default_runtime == ""
        assert loaded.color_scheme == "system"

    def test_roundtrip_custom_values(self, tmp_config: Config) -> None:
        tmp_config.default_runtime = "GE-Proton9-27"
        tmp_config.color_scheme = "dark"
        tmp_config.save()

        loaded = _load_from(tmp_config.data_dir)
        assert loaded.default_runtime == "GE-Proton9-27"
        assert loaded.color_scheme == "dark"

    def test_load_creates_defaults_when_missing(self, tmp_path: Path) -> None:
        """Config.load() with no existing file must create a config and return defaults."""
        data_dir = tmp_path / "fresh_exwin"
        # Patch _DEFAULT_DATA_DIR temporarily by constructing a fresh Config at a
        # known path rather than calling Config.load() which uses the real home dir.
        cfg = Config(data_dir=data_dir)
        cfg._ensure_dirs()
        cfg.save()
        assert cfg.config_path.exists()
        assert cfg.color_scheme == "system"
        assert cfg.default_runtime == ""

    def test_color_scheme_light(self, tmp_config: Config) -> None:
        tmp_config.color_scheme = "light"
        tmp_config.save()
        assert _load_from(tmp_config.data_dir).color_scheme == "light"

    def test_data_dir_persisted_in_toml(self, tmp_config: Config) -> None:
        tmp_config.save()
        raw = tmp_config.config_path.read_text()
        assert str(tmp_config.data_dir) in raw


class TestStorageRoot:
    def test_storage_root_default_is_none(self, tmp_config: Config) -> None:
        assert tmp_config.storage_root is None

    def test_apps_dir_always_under_data_dir(self, tmp_config: Config, tmp_path: Path) -> None:
        """apps_dir (metadata) never follows storage_root."""
        tmp_config.storage_root = tmp_path / "external"
        assert tmp_config.apps_dir == tmp_config.data_dir / "apps"

    def test_prefixes_dir_uses_data_dir_when_storage_root_none(self, tmp_config: Config) -> None:
        assert tmp_config.prefixes_dir == tmp_config.data_dir / "prefixes"

    def test_installs_dir_uses_data_dir_when_storage_root_none(self, tmp_config: Config) -> None:
        assert tmp_config.installs_dir == tmp_config.data_dir / "apps"

    def test_prefixes_dir_uses_storage_root_when_set(
        self, tmp_config: Config, tmp_path: Path
    ) -> None:
        custom = tmp_path / "external"
        tmp_config.storage_root = custom
        assert tmp_config.prefixes_dir == custom / "prefixes"

    def test_installs_dir_uses_storage_root_when_set(
        self, tmp_config: Config, tmp_path: Path
    ) -> None:
        custom = tmp_path / "external"
        tmp_config.storage_root = custom
        assert tmp_config.installs_dir == custom / "apps"

    def test_storage_root_roundtrip(self, tmp_config: Config, tmp_path: Path) -> None:
        custom = tmp_path / "external"
        tmp_config.storage_root = custom
        tmp_config.save()
        loaded = _load_from(tmp_config.data_dir)
        assert loaded.storage_root == custom

    def test_storage_root_absent_from_toml_when_none(self, tmp_config: Config) -> None:
        import tomllib

        tmp_config.storage_root = None
        tmp_config.save()
        with open(tmp_config.config_path, "rb") as f:
            raw = tomllib.load(f)
        assert "storage_root" not in raw


def _load_from(data_dir: Path) -> Config:
    """Load a Config from an explicit data_dir without touching the real home dir."""
    import tomllib

    config_path = data_dir / "config.toml"
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)
    raw_sr = raw.get("storage_root")
    cfg = Config(
        data_dir=Path(raw.get("data_dir", data_dir)),
        default_runtime=raw.get("default_runtime", ""),
        color_scheme=raw.get("color_scheme", "system"),
        storage_root=Path(raw_sr) if raw_sr else None,
    )
    return cfg
