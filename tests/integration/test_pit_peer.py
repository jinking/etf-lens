"""Peer PIT：同类分组必须能回到 as-of 当时的那份快照。"""

from datetime import date

from etf_engine.config.settings import settings
from etf_engine.db.migrate import run_migrations
from etf_engine.repositories.peer_repository import PeerRepository
from etf_engine.services.peer_service import PeerService

T1 = date(2026, 1, 31)
T2 = date(2026, 6, 30)
ASOF = date(2026, 3, 31)


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    repository = PeerRepository()
    repository.upsert_daily_groups(
        [
            {
                "security_id": "510300.SH",
                "asof_date": T1,
                "peer_group_id": "index:000300",
                "kind": "tracking_index",
                "label": "000300",
                "peer_count": 3,
            },
            {
                "security_id": "510300.SH",
                "asof_date": T2,
                "peer_group_id": "index:000510",
                "kind": "tracking_index",
                "label": "000510",
                "peer_count": 5,
            },
        ]
    )


def test_group_asof_returns_the_snapshot_in_effect(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    group = PeerRepository().group_of_asof("510300.SH", asof_date=ASOF)

    assert group["peer_group_id"] == "index:000300", "3 月看到的是 1 月那份快照"
    assert group["peer_count"] == 3


def test_group_asof_after_the_switch_returns_the_new_snapshot(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    group = PeerRepository().group_of_asof("510300.SH", asof_date=date(2026, 7, 31))

    assert group["peer_group_id"] == "index:000510"


def test_group_asof_without_snapshot_returns_none(tmp_path, monkeypatch):
    """as-of 早于第一份快照时不要假装有分组。"""
    _prepare(tmp_path, monkeypatch)

    assert PeerRepository().group_of_asof("510300.SH", asof_date=date(2025, 12, 1)) is None


def test_peer_service_marks_where_the_group_came_from(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    repository = PeerRepository()
    # 当前表里放一份"今天"的分组，用来验证 as-of 查询不会误用它
    repository.upsert_groups(
        [
            {
                "security_id": "510300.SH",
                "peer_group_id": "tag:半导体",
                "kind": "tag",
                "label": "半导体",
                "peer_count": 9,
            }
        ]
    )

    row = PeerService().compare_peers(["510300.SH"], asof_date=ASOF)[0]

    assert row["peer_group_id"] == "index:000300", "优先用 as-of 快照，而不是当前分组"
    assert row["peer_group_pit"] == "asof_snapshot"
