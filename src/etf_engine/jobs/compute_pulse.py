"""看盘台派生层：指数位置分位 + 三层状态。

输入全部是 core 里的事实表；输出进 mart。规则本身在
:mod:`etf_engine.research.market_pulse`（纯函数），这里只负责取数与落库。
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.repositories.index_repository import IndexRepository
from etf_engine.repositories.market_repository import MarketRepository
from etf_engine.research import market_pulse as pulse
from etf_engine.research.market_pulse import (
    DEFAULT_BROAD_INDEX_ID,
    PULSE_VERSION,
    broad_index_ids,
)
from etf_engine.sources.akshare.valuation import ALL_A_INDEX_ID

#: 位置分位窗口（交易日）。
WINDOW_250D = 250
WINDOW_3Y = 750

#: 估值分位的最小样本量（月度观测）。3 年月度数据即可起步。
MIN_VALUATION_SAMPLES = 36
TEN_YEARS_DAYS = 3653


@dataclass(frozen=True, slots=True)
class IndexPosition:
    index_id: str
    trade_date: date
    close: float
    position_pct_250d: float | None
    position_pct_3y: float | None
    drawdown_from_250d_peak: float | None


def compute_index_positions(index_ids: list[str] | None = None) -> list[IndexPosition]:
    """由指数收盘价历史算位置分位与回撤（派生值，进 mart）。"""
    repository = IndexRepository()
    targets = index_ids or [*broad_index_ids(), "000001"]
    history = repository.quote_history(targets, limit=WINDOW_3Y + 50)

    positions: list[IndexPosition] = []
    for index_id, series in history.items():
        closes = [row["close"] for row in series]
        if not closes or series[-1]["trade_date"] is None:
            continue
        window_250 = closes[-WINDOW_250D:]
        peak = max(window_250)
        close = closes[-1]
        positions.append(
            IndexPosition(
                index_id=index_id,
                trade_date=series[-1]["trade_date"],
                close=close,
                position_pct_250d=pulse.percentile_rank(closes, window=WINDOW_250D),
                position_pct_3y=pulse.percentile_rank(closes, window=WINDOW_3Y),
                drawdown_from_250d_peak=None if peak == 0 else (close / peak - 1),
            )
        )
    return positions


def compute_index_valuation_percentiles(index_ids: list[str] | None = None) -> list[dict]:
    """宽基指数滚动 PE 的历史分位（派生值，进 mart）。

    上游给的是月度序列，因此分位按**观测条数**计算；样本不足（<36 条）
    返回 NULL，而不是拿两三个点算出一个"分位"。
    """
    repository = MarketRepository()
    targets = index_ids or broad_index_ids()
    calculated_at = datetime.now().astimezone()
    rows: list[dict] = []

    for index_id in targets:
        series = [
            row for row in repository.index_valuation_series(index_id) if row["pe_ttm"] is not None
        ]
        if not series:
            continue
        latest = series[-1]
        all_values = [row["pe_ttm"] for row in series]
        ten_year_start = latest["trade_date"] - timedelta(days=TEN_YEARS_DAYS)
        recent_values = [row["pe_ttm"] for row in series if row["trade_date"] >= ten_year_start]
        rows.append(
            {
                "index_id": index_id,
                "trade_date": latest["trade_date"],
                "pe_ttm": latest["pe_ttm"],
                "pe_ttm_percentile_all_history": pulse.percentile_rank(
                    all_values, window=len(all_values), min_samples=MIN_VALUATION_SAMPLES
                ),
                "pe_ttm_percentile_10y": pulse.percentile_rank(
                    recent_values,
                    window=len(recent_values),
                    min_samples=MIN_VALUATION_SAMPLES,
                ),
                "observations_all_history": len(all_values),
                "observations_10y": len(recent_values),
                "calculation_version": PULSE_VERSION,
                "calculated_at": calculated_at,
            }
        )
    return rows


def _broad_basket(asof: date) -> dict:
    """宽基 ETF 篮子：跟踪指数在 ``BROAD_BASE_INDICES`` 里的 ETF。

    返回净申购合计与折溢价中位数；同时给出覆盖度，让上层能判断这个篮子
    到底代表了多少只 ETF。
    """
    index_ids = broad_index_ids()
    placeholders = ",".join("?" for _ in index_ids)
    members_sql = f"""
    SELECT DISTINCT etf_id
    FROM core.etf_index_map
    WHERE index_id IN ({placeholders})
      AND (valid_to IS NULL OR valid_to >= ?)
    """
    with connect(settings.database_path) as con:
        member_rows = con.execute(members_sql, [*index_ids, asof]).fetchall()
        members = [row[0] for row in member_rows]
        if not members:
            return {"basket_size": 0, "by_index": {}}

        member_placeholders = ",".join("?" for _ in members)
        flow = con.execute(
            f"""
            WITH latest AS (
                SELECT security_id, estimated_net_subscription_5d,
                       estimated_net_subscription_20d,
                       ROW_NUMBER() OVER (PARTITION BY security_id
                                          ORDER BY trade_date DESC) AS rn
                FROM mart.etf_flow_daily
                WHERE security_id IN ({member_placeholders})
            )
            SELECT SUM(estimated_net_subscription_5d),
                   SUM(estimated_net_subscription_20d),
                   COUNT(*) FILTER (WHERE estimated_net_subscription_5d IS NOT NULL),
                   COUNT(*) FILTER (WHERE estimated_net_subscription_20d IS NOT NULL)
            FROM latest WHERE rn = 1
            """,
            members,
        ).fetchone()

        premium = con.execute(
            f"""
            -- 只用 normalized（正 = 溢价）：上游"基金折价率"单位是百分比且符号相反，
            -- 两者混用会让折价被读成溢价。
            SELECT MEDIAN(q.premium_discount_pct_normalized)
            FROM core.etf_quote_daily q
            WHERE q.security_id IN ({member_placeholders})
              AND q.trade_date = (SELECT MAX(trade_date) FROM core.etf_quote_daily)
            """,
            members,
        ).fetchone()

        premium_coverage = con.execute(
            f"""
            SELECT COUNT(*) FILTER (WHERE q.premium_discount_pct_normalized IS NOT NULL)
            FROM core.etf_quote_daily q
            WHERE q.security_id IN ({member_placeholders})
              AND q.trade_date = (SELECT MAX(trade_date) FROM core.etf_quote_daily)
            """,
            members,
        ).fetchone()

        by_index = con.execute(
            f"""
            SELECT index_id, COUNT(DISTINCT etf_id)
            FROM core.etf_index_map
            WHERE index_id IN ({placeholders})
            GROUP BY index_id ORDER BY index_id
            """,
            index_ids,
        ).fetchall()

    return {
        "basket_size": len(members),
        "member_ids": members,
        "net_subscription_5d": None if flow is None else flow[0],
        "net_subscription_20d": None if flow is None else flow[1],
        "net_subscription_5d_coverage": 0 if flow is None else flow[2],
        "net_subscription_20d_coverage": 0 if flow is None else flow[3],
        "premium_median_pct": None if premium is None else premium[0],
        "premium_coverage": 0 if premium_coverage is None else premium_coverage[0],
        "by_index": {row[0]: row[1] for row in by_index},
    }


def compute_market_pulse(asof: date | None = None) -> dict:
    """计算并写入 ``mart.market_pulse_daily`` 的一行。"""
    market_repository = MarketRepository()
    recorder = IngestionRunRecorder()
    calculated_at = datetime.now().astimezone()
    run_id = recorder.start("market_pulse", "internal_engine", asof)

    try:
        positions = compute_index_positions()
        market_repository.upsert_index_positions(
            [
                {
                    "index_id": item.index_id,
                    "trade_date": item.trade_date,
                    "close": item.close,
                    "position_pct_250d": item.position_pct_250d,
                    "position_pct_3y": item.position_pct_3y,
                    "drawdown_from_250d_peak": item.drawdown_from_250d_peak,
                    "calculation_version": PULSE_VERSION,
                    "calculated_at": calculated_at,
                }
                for item in positions
            ]
        )
        market_repository.upsert_index_valuation_percentiles(compute_index_valuation_percentiles())

        margin_series = market_repository.margin_series(limit=pulse.POSITION_WINDOW)
        turnover_series = market_repository.turnover_series(limit=pulse.POSITION_WINDOW)
        if not turnover_series and asof is None:
            raise ValueError("成交额序列为空：先执行 etf sync-market")

        trade_date = asof or turnover_series[-1]["trade_date"]
        broad_position = next(
            (item for item in positions if item.index_id == DEFAULT_BROAD_INDEX_ID), None
        )

        liquidity = pulse.evaluate_liquidity(margin_series)
        volume = pulse.evaluate_volume(turnover_series)
        basket = _broad_basket(trade_date)
        etf_layer = pulse.evaluate_etf_basket(basket)

        # pulse_v2：原始信号要连续 CONFIRM_DAYS 天才算确认切换，
        # 因此日更需要读上一行的"确认状态 + 原始信号"。
        previous = market_repository.pulse_before(trade_date)
        confirmed_states = {
            key: pulse.step_confirmed(
                confirmed_prev=(previous or {}).get(f"{key}_state"),
                raw_prev=(previous or {}).get(f"{key}_raw_state"),
                raw_today=layer.state.value,
            )
            for key, layer in (
                ("liquidity", liquidity),
                ("volume", volume),
                ("etf", etf_layer),
            )
        }

        row = pulse.build_pulse_row(
            trade_date=trade_date,
            liquidity=liquidity,
            volume=volume,
            etf=etf_layer,
            basket=basket,
            broad_index_id=DEFAULT_BROAD_INDEX_ID,
            broad_index_position_pct_250d=(
                None if broad_position is None else broad_position.position_pct_250d
            ),
            activity=market_repository.latest_activity(),
            calculated_at=calculated_at,
            confirmed_states=confirmed_states,
        )
        market_repository.upsert_pulse(row)
        recorder.finish(
            run_id,
            status="SUCCESS",
            rows_fetched=1,
            rows_written=1,
            rows_rejected=0,
        )
        return {
            "run_id": run_id,
            "trade_date": trade_date,
            "overall_state": row["overall_state"],
            "layers": {
                "liquidity": liquidity.state.value,
                "volume": volume.state.value,
                "etf": etf_layer.state.value,
            },
            "basket_size": basket.get("basket_size"),
            "valuation": market_repository.latest_valuation(ALL_A_INDEX_ID),
        }
    except Exception as exc:
        recorder.finish(
            run_id,
            status="FAILED",
            rows_fetched=0,
            rows_written=0,
            rows_rejected=0,
            error_message=str(exc),
        )
        raise


def _basket_sums_by_date(index_ids: list[str], asof: date) -> dict[date, dict]:
    """篮子逐日净申购合计（供历史回放）。

    篮子成员口径：按**当前**的 ``core.etf_index_map`` 取。成员变动没有回溯，
    这点在历史上是近似，必须在文档与界面上写清楚。
    """
    placeholders = ",".join("?" for _ in index_ids)
    sql = f"""
    WITH members AS (
        SELECT DISTINCT etf_id
        FROM core.etf_index_map
        WHERE index_id IN ({placeholders})
          AND (valid_to IS NULL OR valid_to >= ?)
    )
    SELECT f.trade_date,
           SUM(f.estimated_net_subscription_5d),
           SUM(f.estimated_net_subscription_20d)
    FROM mart.etf_flow_daily f
    JOIN members m ON m.etf_id = f.security_id
    GROUP BY f.trade_date
    ORDER BY f.trade_date
    """
    with connect(settings.database_path) as con:
        rows = con.execute(sql, [*index_ids, asof]).fetchall()
    return {row[0]: {"net_subscription_5d": row[1], "net_subscription_20d": row[2]} for row in rows}


def backfill_pulse_history(
    days: int = 250,
    asof: date | None = None,
) -> dict:
    """逐日回放三层状态，写入 ``mart.market_pulse_daily``（供热力图）。

    口径说明（与实时计算一致，不因为是回放而放宽）：

    * 第一层用两融余额序列按日截断；第二层用成交额序列按日截断，
      位置分位只用到当日为止的收盘价；
    * 第三层用 ``mart.etf_flow_daily`` 的历史（由 ``etf backfill-flow`` 回填），
      **篮子成员按当前口径**，成员变动未回溯；
    * 折溢价依赖 IOPV 快照，只有最新一天有值，历史行为 NULL；
    * 回放行是"用今天存下的事实按同一条规则重算"，不是当时写下的快照——
      如果上游后来修正过历史事实，回放结果会与当日所见不同。
    """
    market_repository = MarketRepository()
    recorder = IngestionRunRecorder()
    calculated_at = datetime.now().astimezone()
    run_id = recorder.start("market_pulse_backfill", "internal_engine", asof)

    try:
        margin_series = market_repository.margin_series(limit=400)
        turnover_series = market_repository.turnover_series(limit=400)
        if not turnover_series:
            raise ValueError("成交额序列为空：先执行 etf sync-market")
        turnover_series = turnover_series[-days:]

        index_id = DEFAULT_BROAD_INDEX_ID
        closes = IndexRepository().quote_history([index_id], limit=1500).get(index_id, [])
        closes_by_date = {row["trade_date"]: row["close"] for row in closes}
        ordered_close_dates = sorted(closes_by_date)

        last_date = turnover_series[-1]["trade_date"]
        basket_size = len(market_repository.basket_member_ids(broad_index_ids(), last_date))
        sums_by_date = _basket_sums_by_date(broad_index_ids(), last_date)
        latest_quote_date = market_repository.latest_quote_date()
        premium_median = (
            market_repository.basket_premium_median(broad_index_ids(), latest_quote_date)
            if latest_quote_date
            else None
        )

        # 先算每一天的原始信号，再整段做确认（pulse_v2 的确认机制是跨天的，
        # 逐日单独算不出"连续几天"这个条件）。
        raw_entries: list[dict] = []
        for turnover_row in turnover_series:
            trade_date = turnover_row["trade_date"]
            margin_prefix = [row for row in margin_series if row["trade_date"] <= trade_date]
            turnover_prefix = [row for row in turnover_series if row["trade_date"] <= trade_date]
            past_closes = [
                closes_by_date[value] for value in ordered_close_dates if value <= trade_date
            ]
            position = pulse.percentile_rank(past_closes)

            liquidity = pulse.evaluate_liquidity(margin_prefix)
            volume = pulse.evaluate_volume(turnover_prefix)
            basket = {
                "basket_size": basket_size,
                "net_subscription_5d": sums_by_date.get(trade_date, {}).get("net_subscription_5d"),
                "net_subscription_20d": sums_by_date.get(trade_date, {}).get(
                    "net_subscription_20d"
                ),
                "premium_median_pct": (premium_median if trade_date == latest_quote_date else None),
            }
            etf_layer = pulse.evaluate_etf_basket(basket)
            raw_entries.append(
                {
                    "trade_date": trade_date,
                    "liquidity": liquidity,
                    "volume": volume,
                    "etf": etf_layer,
                    "basket": basket,
                    "position": position,
                }
            )

        confirmed_series = {
            key: pulse.confirm_states([entry[key].state.value for entry in raw_entries])
            for key in ("liquidity", "volume", "etf")
        }

        rows: list[dict] = []
        for index, entry in enumerate(raw_entries):
            rows.append(
                pulse.build_pulse_row(
                    trade_date=entry["trade_date"],
                    liquidity=entry["liquidity"],
                    volume=entry["volume"],
                    etf=entry["etf"],
                    basket=entry["basket"],
                    broad_index_id=index_id,
                    broad_index_position_pct_250d=entry["position"],
                    activity=None,
                    calculated_at=calculated_at,
                    confirmed_states={
                        key: confirmed_series[key][index] for key in confirmed_series
                    },
                )
            )

        for row in rows:
            market_repository.upsert_pulse(row)

        recorder.finish(
            run_id,
            status="SUCCESS",
            rows_fetched=len(rows),
            rows_written=len(rows),
            rows_rejected=0,
        )
        return {
            "run_id": run_id,
            "rows_written": len(rows),
            "date_range": [
                rows[0]["trade_date"].isoformat(),
                rows[-1]["trade_date"].isoformat(),
            ],
            "basket_size": basket_size,
            "etf_layer_dates": len(sums_by_date),
        }
    except Exception as exc:
        recorder.finish(
            run_id,
            status="FAILED",
            rows_fetched=0,
            rows_written=0,
            rows_rejected=0,
            error_message=str(exc),
        )
        raise
