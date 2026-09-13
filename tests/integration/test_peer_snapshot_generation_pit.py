"""历史 Peer 快照生成 PIT 约束测试。

验证 compute_peer_metrics(asof=T)：
1. T1 Tag=A，T2 Tag=B，查询 T1.5 时按 A 分组；
2. 费率在 T2 才观测，T1 快照的 fee rank 必须为 NULL；
3. 同日 v1/v2 Flow 并存，Peer rank 必须基于 flow_v2；
4. Tracking Index 在 T2 才观测，T1 快照不得使用 T2 mapping 或 fallback 到当前 master。
"""

from datetime import date, datetime
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFMaster, ETFQuote, SourceMeta
from etf_engine.domain.versions import current_flow_version
from etf_engine.jobs.compute_peer_metrics import compute_peer_metrics
from etf_engine.repositories.index_repository import IndexRepository
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.tag_repository import TagRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository

T1 = date(2026, 9, 1)
T1_5 = date(2026, 9, 5)
T2 = date(2026, 9, 10)
FETCHED_AT = datetime(2026, 9, 1, 10, 0)


def _meta() -> SourceMeta:
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


def _setup_three_etfs(tmp_path, monkeypatch, asof: date = T1) -> list[str]:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    calendar_dates = [T1, T1_5, T2]
    TradingCalendarRepository().upsert_many(calendar_dates, source="test", upstream_source="test")

    sec_ids = ["510300.SH", "159919.SZ", "510310.SH"]
    masters = [
        ETFMaster(
            security_id=sid,
            ticker=sid.split(".")[0],
            exchange="SSE" if sid.endswith(".SH") else "SZSE",
            fund_name=f"ETF-{sid}",
            source_meta=_meta(),
        )
        for sid in sec_ids
    ]
    MasterRepository().upsert_many(masters)

    quotes = []
    for sid in sec_ids:
        quotes.append(
            ETFQuote(
                security_id=sid,
                trade_date=asof,
                close=Decimal("3.5"),
                turnover_amount=Decimal("1000000"),
                source_meta=_meta(),
            )
        )
    QuoteRepository().upsert_many(quotes)
    return sec_ids


def test_peer_grouping_uses_pit_tag(tmp_path, monkeypatch):
    """1. T1 Tag=A，T2 Tag=B，查询 T1.5，按 A 分组。"""
    sec_ids = _setup_three_etfs(tmp_path, monkeypatch, asof=T1_5)

    # 写入两段 tag：T1 启用的 Tag-A (valid_to=T2)，T2 启用的 Tag-B (valid_to=None)
    TagRepository().upsert_tags(
        [
            {
                "etf_id": sid,
                "tag": "行业A",
                "tag_type": "industry",
                "source": "test",
                "valid_from": T1,
                "valid_to": T2,
            }
            for sid in sec_ids
        ]
        + [
            {
                "etf_id": sid,
                "tag": "行业B",
                "tag_type": "industry",
                "source": "test",
                "valid_from": T2,
                "valid_to": None,
            }
            for sid in sec_ids
        ]
    )

    compute_peer_metrics(asof=T1_5)

    with connect(settings.database_path) as con:
        rows = con.execute(
            """
            SELECT security_id, peer_group_id FROM mart.etf_peer_group_daily
            WHERE asof_date = ?
            """,
            [T1_5],
        ).fetchall()

    assert len(rows) == 3
    for _, group_id in rows:
        assert group_id == "tag:行业A", f"T1.5 应按 PIT 生效的 行业A 分组，实际: {group_id}"


def test_fee_rank_is_null_when_fee_observed_after_asof(tmp_path, monkeypatch):
    """2. Fee 在 T2 才观测，T1 snapshot 的 fee rank 必须 NULL。"""
    sec_ids = _setup_three_etfs(tmp_path, monkeypatch, asof=T1)

    # 在 T1 时刻 index_map 已存在，使 3 只 ETF 能按 index:000300 聚合成组
    IndexRepository().upsert_map(
        [
            {
                "etf_id": sid,
                "index_id": "000300",
                "index_name": "沪深300",
                "valid_from": T1,
                "source": "test",
            }
            for sid in sec_ids
        ]
    )

    # master 表上登记费率，但观测时间 profile_observed_at 在 T2 (晚于 asof=T1)
    with connect(settings.database_path) as con:
        con.execute(
            """
            UPDATE core.etf_master
            SET management_fee_pct = 0.5,
                profile_observed_at = ?
            WHERE security_id IN (?, ?, ?)
            """,
            [datetime(2026, 9, 10, 15, 0), *sec_ids],
        )

    compute_peer_metrics(asof=T1)

    with connect(settings.database_path) as con:
        rows = con.execute(
            """
            SELECT security_id, fee_rank_pct FROM mart.etf_peer_metric_daily
            WHERE asof_date = ?
            """,
            [T1],
        ).fetchall()

    assert len(rows) == 3
    for sid, fee_rank in rows:
        assert fee_rank is None, f"{sid} 在 T1 的费率观测于 T2，快照中 fee_rank_pct 必须为 NULL"


def test_flow_rank_uses_flow_v2_over_v1(tmp_path, monkeypatch):
    """3. 同日 v1/v2 Flow 并存，Peer rank 必须基于 flow_v2。"""
    sec_ids = _setup_three_etfs(tmp_path, monkeypatch, asof=T1)

    IndexRepository().upsert_map(
        [
            {
                "etf_id": sid,
                "index_id": "000300",
                "index_name": "沪深300",
                "valid_from": T1,
                "source": "test",
            }
            for sid in sec_ids
        ]
    )

    # 写入 Flow：
    # v1: 510300=100 (最低), 159919=200, 510310=300 (最高)
    # v2: 510300=300 (最高), 159919=200, 510310=100 (最低)
    with connect(settings.database_path) as con:
        con.executemany(
            """
            INSERT INTO mart.etf_flow_daily
                (security_id, trade_date, share_change_20d, is_estimated,
                 calculation_version, calculated_at)
            VALUES (?, ?, ?, TRUE, ?, ?)
            """,
            [
                ("510300.SH", T1, 100.0, "flow_v1", FETCHED_AT),
                ("159919.SZ", T1, 200.0, "flow_v1", FETCHED_AT),
                ("510310.SH", T1, 300.0, "flow_v1", FETCHED_AT),
                ("510300.SH", T1, 300.0, current_flow_version(), FETCHED_AT),
                ("159919.SZ", T1, 200.0, current_flow_version(), FETCHED_AT),
                ("510310.SH", T1, 100.0, current_flow_version(), FETCHED_AT),
            ],
        )

    compute_peer_metrics(asof=T1)

    with connect(settings.database_path) as con:
        rows = dict(
            con.execute(
                """
                SELECT security_id, flow_rank_pct FROM mart.etf_peer_metric_daily
                WHERE asof_date = ?
                """,
                [T1],
            ).fetchall()
        )

    assert rows["510300.SH"] == 1.0, (
        f"510300.SH 在 flow_v2 最高，flow_rank 必须为 1.0，实际: {rows['510300.SH']}"
    )
    assert rows["510310.SH"] == 0.0, (
        f"510310.SH 在 flow_v2 最低，flow_rank 必须为 0.0，实际: {rows['510310.SH']}"
    )


def test_tracking_index_not_used_when_observed_after_asof(tmp_path, monkeypatch):
    """4. Tracking Index 在 T2 才观测，T1 快照不得使用 T2 mapping，也不得 fallback 到 master。"""
    sec_ids = _setup_three_etfs(tmp_path, monkeypatch, asof=T1)

    # master 表上有 tracking_index（当前状态）
    with connect(settings.database_path) as con:
        con.execute(
            """
            UPDATE core.etf_master
            SET tracking_index_id = '000300',
                tracking_index_name = '沪深300'
            WHERE security_id IN (?, ?, ?)
            """,
            sec_ids,
        )

    # 映射表中该 tracking index 在 T2 才能被观测
    IndexRepository().upsert_map(
        [
            {
                "etf_id": sid,
                "index_id": "000300",
                "index_name": "沪深300",
                "valid_from": T2,  # 晚于 T1
                "source": "test",
            }
            for sid in sec_ids
        ]
    )

    compute_peer_metrics(asof=T1)

    with connect(settings.database_path) as con:
        rows = con.execute(
            """
            SELECT security_id, peer_group_id FROM mart.etf_peer_group_daily
            WHERE asof_date = ?
            """,
            [T1],
        ).fetchall()

    # T1 找不到 PIT-safe 的 index mapping，禁止 fallback 当前 master，因此不能按 index:000300 分组
    for sid, group_id in rows:
        assert group_id != "index:000300", (
            f"{sid} 的指数在 T2 才观测，T1 快照不得使用 index:000300 分组"
        )
