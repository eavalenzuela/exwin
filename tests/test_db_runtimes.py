"""Tests for exwin.db.runtimes."""

from __future__ import annotations

from pathlib import Path

from exwin.backend.config import Config
from exwin.backend.runtime import Runtime
from exwin.db.runtimes import get_all_runtimes, get_runtime, sync_runtimes, upsert_runtime
from exwin.models import RuntimeType


class TestUpsertRuntime:
    def test_insert_new(self, db: Config) -> None:
        rt = Runtime(
            name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"), version="9.0"
        )
        db_id = upsert_runtime(rt)
        assert db_id > 0

    def test_update_existing(self, db: Config) -> None:
        rt = Runtime(
            name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"), version="9.0"
        )
        id1 = upsert_runtime(rt)

        rt.name = "Proton 9 Updated"
        rt.version = "9.1"
        id2 = upsert_runtime(rt)

        assert id1 == id2  # same path = same record
        fetched = get_runtime(id1)
        assert fetched is not None
        assert fetched.name == "Proton 9 Updated"
        assert fetched.version == "9.1"

    def test_different_paths_get_different_ids(self, db: Config) -> None:
        rt1 = Runtime(
            name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton9"), version="9"
        )
        rt2 = Runtime(
            name="Proton 10", type=RuntimeType.PROTON, path=Path("/opt/proton10"), version="10"
        )
        id1 = upsert_runtime(rt1)
        id2 = upsert_runtime(rt2)
        assert id1 != id2


class TestGetRuntime:
    def test_returns_none_for_missing(self, db: Config) -> None:
        assert get_runtime(99999) is None

    def test_returns_runtime(self, db: Config) -> None:
        rt = Runtime(name="Wine", type=RuntimeType.WINE, path=Path("/usr"), version="wine-9.0")
        db_id = upsert_runtime(rt)
        fetched = get_runtime(db_id)
        assert fetched is not None
        assert fetched.name == "Wine"
        assert fetched.type == RuntimeType.WINE
        assert fetched.path == Path("/usr")


class TestGetAllRuntimes:
    def test_empty_initially(self, db: Config) -> None:
        assert get_all_runtimes() == []

    def test_returns_all(self, db: Config) -> None:
        upsert_runtime(Runtime(name="A", type=RuntimeType.PROTON, path=Path("/a"), version="1"))
        upsert_runtime(Runtime(name="B", type=RuntimeType.WINE, path=Path("/b"), version="2"))
        all_rt = get_all_runtimes()
        assert len(all_rt) == 2


class TestSyncRuntimes:
    def test_populates_db_ids(self, db: Config) -> None:
        runtimes = [
            Runtime(
                name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"), version="9"
            ),
            Runtime(name="Wine", type=RuntimeType.WINE, path=Path("/usr"), version="wine-9"),
        ]
        result = sync_runtimes(runtimes)
        assert len(result) == 2
        assert all(rt.db_id is not None for rt in result)
        assert result[0].db_id != result[1].db_id

    def test_idempotent(self, db: Config) -> None:
        runtimes = [
            Runtime(
                name="Proton 9", type=RuntimeType.PROTON, path=Path("/opt/proton"), version="9"
            ),
        ]
        r1 = sync_runtimes(runtimes)
        r2 = sync_runtimes(runtimes)
        assert r1[0].db_id == r2[0].db_id

    def test_preserves_fields(self, db: Config) -> None:
        runtimes = [
            Runtime(
                name="GE-Proton9-27",
                type=RuntimeType.PROTON,
                path=Path("/steam/ge"),
                version="GE-Proton9-27",
            ),
        ]
        result = sync_runtimes(runtimes)
        assert result[0].name == "GE-Proton9-27"
        assert result[0].type == RuntimeType.PROTON
        assert result[0].path == Path("/steam/ge")
        assert result[0].version == "GE-Proton9-27"
