"""看盘台端到端（打桩数据，不访问网络）。

覆盖：市场层入库 → 三层规则 → mart 落库 → API 输出 → 页面可读。
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from etf_engine.api import app as api_module
from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import Exchange, QualityStatus
from etf_engine.domain.models import MarginBalance, MarketActivity, MarketTurnover, SourceMeta
from etf_engine.jobs.compute_pulse import compute_market_pulse
from etf_engine.repositories.market_repository import MarketRepository

FETCHED_AT = datetime(2026, 9, 12, 10, 0)
DAYS = 80
START = date(2026, 5, 1)


def _meta(source: str) -> SourceMeta:
    return SourceMeta(
        source=source,
        upstream_source=source,
        fetched_at=FETCHED_AT,
        quality_status=QualityStatus.PASS,
    )


def _seed_market(database_path) -> date:
    """写入 80 个交易日的沪深成交额与两融余额，最后一天的成交额放量。"""
    turnover_repo = MarketRepository()
    last_day = START
    for index in range(DAYS):
        day = START + timedelta(days=index)
        last_day = day
        base = 5e11 if index < DAYS - 1 else 1.2e12
        turnover_repo.upsert_turnover(
            [
                MarketTurnover(
                    trade_date=day,
                    exchange=Exchange.SSE,
                    turnover_amount=Decimal(str(base)),
                    turnover_rate_pct=Decimal("1.39"),
                    float_market_cap=Decimal("6.0e13"),
                    listing_count=Decimal("2359"),
                    source_meta=_meta("sse"),
                ),
                MarketTurnover(
                    trade_date=day,
                    exchange=Exchange.SZSE,
                    turnover_amount=Decimal(str(base * 1.05)),
                    turnover_rate_pct=None,
                    float_market_cap=Decimal("3.7e13"),
                    listing_count=Decimal("2939"),
                    source_meta=_meta("szse"),
                ),
            ]
        )
        balance = 1.2e12 + index * 1e10
        turnover_repo.upsert_margin(
            [
                MarginBalance(
                    trade_date=day,
                    exchange=Exchange.SSE,
                    financing_balance=Decimal(str(balance)),
                    margin_balance=Decimal(str(balance * 1.01)),
                    source_meta=_meta("akshare_margin_sse"),
                ),
                MarginBalance(
                    trade_date=day,
                    exchange=Exchange.SZSE,
                    financing_balance=Decimal(str(balance * 0.95)),
                    margin_balance=Decimal(str(balance * 0.96)),
                    source_meta=_meta("akshare_margin_szse"),
                ),
            ]
        )
    turnover_repo.upsert_activity(
        [
            MarketActivity(
                trade_date=last_day,
                rising_count=Decimal("604"),
                falling_count=Decimal("4567"),
                flat_count=Decimal("36"),
                limit_up_count=Decimal("40"),
                limit_down_count=Decimal("21"),
                activity_pct=Decimal("11.57"),
                statistic_at=FETCHED_AT,
                source_meta=_meta("akshare_legu"),
            )
        ]
    )
    return last_day


def _seed_basket(database_path, asof: date) -> None:
    """一只沪深300 ETF + 一只通信 ETF（后者不该进篮子）。"""
    with connect(database_path) as con:
        con.executemany(
            "INSERT INTO core.etf_master (security_id, ticker, exchange, short_name)"
            " VALUES (?,?,?,?)",
            [
                ("510300.SH", "510300", "SSE", "华泰柏瑞沪深300ETF"),
                ("510500.SH", "510500", "SSE", "南方中证500ETF"),
                ("515880.SH", "515880", "SSE", "国泰中证全指通信设备ETF"),
            ],
        )
        con.executemany(
            "INSERT INTO core.etf_index_map"
            " (etf_id, index_id, index_name, valid_from, valid_to, source)"
            " VALUES (?,?,?,?,?,?)",
            [
                ("510300.SH", "000300", "沪深300指数", asof, None, "fund_benchmark"),
                # 同一指数的另一种目录口径（新浪符号码）：必须同样进篮子
                ("510500.SH", "399905", "中证 500", asof, None, "fund_benchmark"),
                ("515880.SH", "931160", "中证全指通信设备指数", asof, None, "fund_benchmark"),
            ],
        )
        con.execute(
            "INSERT INTO core.index_catalog"
            " (index_id, index_name, market_symbol, source, fetched_at)"
            " VALUES ('000300','沪深300指数','sh000300','csindex',?)",
            [FETCHED_AT],
        )
        con.executemany(
            "INSERT INTO core.etf_share_daily"
            " (security_id, trade_date, shares, nav, estimated_aum, is_estimated_aum,"
            "  source, fetched_at, quality_status)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("510300.SH", asof, 2.3e10, 4.6, 1.07e11, True, "sse", FETCHED_AT, "PASS"),
            ],
        )
        con.executemany(
            "INSERT INTO mart.etf_flow_daily"
            " (security_id, trade_date, estimated_net_subscription_5d,"
            "  estimated_net_subscription_20d, estimated_net_subscription_1d,"
            "  is_estimated, calculation_version, calculated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [
                ("510300.SH", asof, 5.0e8, 1.2e9, 3.0e8, True, "flow_v1", FETCHED_AT),
                # 前一个交易日：累积曲线需要至少两个点
                (
                    "510300.SH",
                    asof - timedelta(days=1),
                    4.0e8,
                    9.0e8,
                    1.0e8,
                    True,
                    "flow_v1",
                    FETCHED_AT,
                ),
            ],
        )
        con.executemany(
            "INSERT INTO core.etf_quote_daily"
            " (security_id, trade_date, close, change_pct, turnover_amount,"
            "  premium_discount_pct, premium_discount_pct_normalized,"
            "  source, fetched_at, quality_status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                # 只写 normalized（正 = 溢价）；上游"基金折价率"字段符号相反，
                # 这里刻意留成另一个值，验证看盘台不会去用它
                ("510300.SH", asof, 4.6, 0.5, 3.0e9, 0.55, 0.0015, "eastmoney", FETCHED_AT, "PASS")
            ],
        )


def test_watchboard_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    asof = _seed_market(settings.database_path)
    _seed_basket(settings.database_path, asof)

    result = compute_market_pulse(asof=asof)
    payload = TestClient(api_module.app).get("/api/v1/watchboard").json()
    data = payload["data"]

    assert result["trade_date"] == asof
    assert [layer["key"] for layer in data["layers"]] == ["liquidity", "volume", "etf"]
    assert data["meta"]["asof_date"] == asof.isoformat()
    assert data["meta"]["calculation_version"] == "pulse_v2"

    volume_layer = data["layers"][1]
    assert volume_layer["state"] == "STRONG"
    assert volume_layer["facts"][0]["value"] > 2e12  # 沪深合计

    liquidity_layer = data["layers"][0]
    assert liquidity_layer["state"] in {"STRONG", "NEUTRAL", "WEAK"}
    # 深市换手率缺失必须体现为 NULL，而不是 0
    assert data["turnover_series"][0]["turnover_rate_pct"] == 1.39

    # 成交额序列必须带 20 日均额：前 19 个点窗口不足 → NULL，之后有值
    averages = [row["turnover_amount_20d_avg"] for row in data["turnover_series"]]
    assert averages[:19] == [None] * 19
    assert averages[-1] is not None and averages[-1] > 0

    # 篮子只包含跟踪宽基指数的 ETF
    assert data["meta"]["broad_index"]["index_id"] == "000300"
    basket_ids = {row["security_id"] for row in data["basket"]}
    # 通信设备 ETF 不进篮子；中证 500 的两种目录口径都要进
    assert basket_ids == {"510300.SH", "510500.SH"}
    h300 = next(row for row in data["basket"] if row["security_id"] == "510300.SH")
    assert h300["net_subscription_5d"] == 5.0e8
    # 折溢价只取 normalized（0.0015 = +0.15%），不取符号相反的上游折价率 0.55
    assert h300["premium_pct"] == pytest.approx(0.0015)

    # 篮子净申购累积曲线：按跟踪指数分组，逐日累加
    flow = data["basket_flow"]
    assert [item["index_name"] for item in flow["series"]] == ["沪深300"]
    h300_series = flow["series"][0]
    assert len(h300_series["points"]) == 2
    assert h300_series["cumulative_net_subscription"] == pytest.approx(4.0e8)
    # 只有一只成员、有两只就画出曲线；科创50 / 中证1000 / 创业板指没有成员数据
    assert "科创50" in flow["skipped_index_names"]
    assert data["activity"]["rising_count"] == 604


def test_watchboard_empty_state_is_honest(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()

    payload = TestClient(api_module.app).get("/api/v1/watchboard").json()

    assert payload["data"]["meta"]["quality"] == "EMPTY"
    assert payload["data"]["layers"] == []
    assert payload["data"]["gaps"]  # 缺口说明必须随空状态一起返回


def test_watchboard_page_is_served(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()

    response = TestClient(api_module.app).get("/watchboard")

    assert response.status_code == 200
    assert "看盘台" in response.text
