"""Tests for exwin.backend.gog_metadata."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from exwin.backend.config import Config
from exwin.backend.gog_metadata import _strip_html, apply_custom_cover_art
from exwin.db.schema import init_db

# ---------------------------------------------------------------------------
# Minimal 1×1 PNG bytes — used for b64 and local-file tests
# ---------------------------------------------------------------------------
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAABjE+ibYAAAAASUVORK5CYII="
)
_PNG_DATA_URI = "data:image/png;base64," + base64.b64encode(_PNG_BYTES).decode()
_JPEG_DATA_URI = "data:image/jpeg;base64," + base64.b64encode(_PNG_BYTES).decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_config(tmp_path: Path) -> Config:
    """Config + initialised DB in a temp dir."""
    cfg = Config(data_dir=tmp_path / "exwin")
    cfg._ensure_dirs()
    init_db(cfg.data_dir)
    # Seed a minimal app row so update_cover_art has something to update.
    from exwin.db.apps import insert_app
    from exwin.models import AppEntry

    insert_app(AppEntry(app_id="test-app", name="Test App", source="gog"))
    return cfg


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------


class TestStripHtml:
    def test_removes_tags(self) -> None:
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_decodes_amp(self) -> None:
        assert _strip_html("A &amp; B") == "A & B"

    def test_decodes_lt_gt(self) -> None:
        assert _strip_html("&lt;tag&gt;") == "<tag>"

    def test_decodes_quot(self) -> None:
        assert _strip_html("say &quot;hi&quot;") == 'say "hi"'

    def test_decodes_apos(self) -> None:
        assert _strip_html("it&#39;s") == "it's"

    def test_decodes_nbsp(self) -> None:
        assert _strip_html("a&nbsp;b") == "a b"

    def test_collapses_whitespace(self) -> None:
        assert _strip_html("a   b\n\nc") == "a b c"

    def test_empty_string(self) -> None:
        assert _strip_html("") == ""

    def test_no_html(self) -> None:
        assert _strip_html("plain text") == "plain text"


# ---------------------------------------------------------------------------
# apply_custom_cover_art — base64 data URIs
# ---------------------------------------------------------------------------


class TestApplyCustomCoverArtB64:
    def test_png_data_uri_writes_file(self, db_config: Config) -> None:
        result = apply_custom_cover_art("test-app", _PNG_DATA_URI, db_config)
        dst = Path(result)
        assert dst.exists()
        assert dst.read_bytes() == _PNG_BYTES

    def test_jpeg_data_uri_writes_file(self, db_config: Config) -> None:
        result = apply_custom_cover_art("test-app", _JPEG_DATA_URI, db_config)
        assert Path(result).read_bytes() == _PNG_BYTES

    def test_returns_path_string(self, db_config: Config) -> None:
        result = apply_custom_cover_art("test-app", _PNG_DATA_URI, db_config)
        assert isinstance(result, str)
        assert result.endswith("cover.jpg")

    def test_dest_under_metadata_dir(self, db_config: Config) -> None:
        result = apply_custom_cover_art("test-app", _PNG_DATA_URI, db_config)
        expected = db_config.metadata_dir / "test-app" / "cover.jpg"
        assert Path(result) == expected

    def test_updates_db(self, db_config: Config) -> None:
        from exwin.db.apps import get_app

        apply_custom_cover_art("test-app", _PNG_DATA_URI, db_config)
        app = get_app("test-app")
        assert app is not None
        assert app.cover_art_path.endswith("cover.jpg")

    def test_invalid_b64_raises(self, db_config: Config) -> None:
        bad_uri = "data:image/png;base64,NOT_VALID_BASE64!!!"
        with pytest.raises(ValueError, match="Invalid base64"):
            apply_custom_cover_art("test-app", bad_uri, db_config)

    def test_creates_metadata_subdir(self, db_config: Config, tmp_path: Path) -> None:
        """Metadata dir for app-id must be created on demand."""
        apply_custom_cover_art("test-app", _PNG_DATA_URI, db_config)
        assert (db_config.metadata_dir / "test-app").is_dir()


# ---------------------------------------------------------------------------
# apply_custom_cover_art — local file
# ---------------------------------------------------------------------------


class TestApplyCustomCoverArtLocalFile:
    def test_copies_file(self, db_config: Config, tmp_path: Path) -> None:
        src = tmp_path / "art.jpg"
        src.write_bytes(_PNG_BYTES)
        result = apply_custom_cover_art("test-app", str(src), db_config)
        assert Path(result).read_bytes() == _PNG_BYTES

    def test_missing_file_raises(self, db_config: Config, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            apply_custom_cover_art("test-app", str(tmp_path / "nope.jpg"), db_config)


# ---------------------------------------------------------------------------
# fetch_metadata — network-free edge cases
# ---------------------------------------------------------------------------


class TestFetchMetadata:
    def test_empty_game_id_returns_empty_dict(self) -> None:
        from exwin.backend.gog_metadata import fetch_metadata

        assert fetch_metadata("") == {}
