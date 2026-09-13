from datetime import date

import pandas as pd

from etf_engine.domain.core_metrics import CoreMetricsQuality, ETFCoreMetrics, TrackingIndex
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.versions import current_flow_version, current_metric_version
from etf_engine.ingestion.normalizer import normalize_premium_discount
from etf_engine.repositories.core_metrics_repository import CoreMetricsRepository
from etf_engine.research.corporate_actions import has_unadjusted_jump
from etf_engine.research.exposure import calculate_top10_concentration
from etf_engine.research.liquidity import bid_ask_spread as calculate_bid_ask_spread
from etf_engine.research.tracking import tracking_error


class ETFCoreMetricsService:
    def __init__(self, repository: CoreMetricsRepository | None = None):
        self.repository = repository or CoreMetricsRepository()

    def get_core_metrics(self, security_id: str, asof_date: date | None = None) -> ETFCoreMetrics:
        canonical_id = SecurityId.parse(security_id).value
        quote_rows = self.repository.quote_history(canonical_id, asof_date)
        if not quote_rows:
            raise LookupError(f"本地尚未找到 {canonical_id} 的行情数据")

        latest_quote = quote_rows[-1]
        effective_asof = latest_quote["trade_date"]
        reasons: dict[str, str] = {}
        source_asof_dates: dict[str, date | None] = {"quote": effective_asof}

        premium_discount = latest_quote.get("premium_discount_pct_normalized")
        if premium_discount is None:
            premium_discount = normalize_premium_discount(
                latest_quote.get("close"), latest_quote.get("iopv")
            )
        if premium_discount is None:
            reasons["premium_discount_pct"] = "iopv_unavailable"

        spread_value = calculate_bid_ask_spread(latest_quote.get("bid1"), latest_quote.get("ask1"))
        if latest_quote.get("bid1") is None:
            reasons["bid1"] = "bid1_unavailable"
        if latest_quote.get("ask1") is None:
            reasons["ask1"] = "ask1_unavailable"
        if spread_value is None:
            reasons["bid_ask_spread_pct"] = "bid_ask_unavailable_or_invalid"
            bid_ask_spread = bid_ask_spread_pct = None
        else:
            bid_ask_spread, bid_ask_spread_pct = spread_value

        # ---- 消费 metric_v2 ----
        metric_row = self.repository.metric_asof(
            canonical_id, effective_asof, current_metric_version()
        )
        if metric_row:
            source_asof_dates["metric"] = metric_row.get("trade_date")
            market_return_20d = metric_row.get("return_20d")
            market_return_60d = metric_row.get("return_60d")
            max_drawdown_60d = metric_row.get("max_drawdown_60d")
            avg_turnover = metric_row.get("avg_turnover_amount_20d")
        else:
            source_asof_dates["metric"] = None
            market_return_20d = None
            market_return_60d = None
            max_drawdown_60d = None
            avg_turnover = None

        if latest_quote.get("turnover_amount") is None:
            reasons["turnover_amount"] = "turnover_amount_unavailable"
        if avg_turnover is None:
            reasons["avg_turnover_amount_20d"] = "insufficient_history"

        for metric_name, value in (
            ("market_return_20d", market_return_20d),
            ("market_return_60d", market_return_60d),
            ("max_drawdown_60d", max_drawdown_60d),
        ):
            if value is None:
                reasons[metric_name] = "insufficient_history"

        master = self.repository.master(canonical_id)
        tracking_index_row = self.repository.tracking_index(canonical_id, effective_asof)
        tracking_index = TrackingIndex(
            id=tracking_index_row.get("index_id") if tracking_index_row else None,
            name=tracking_index_row.get("index_name") if tracking_index_row else None,
            source=tracking_index_row.get("source") if tracking_index_row else None,
        )
        if tracking_index.id is None:
            reasons["tracking_index"] = "tracking_index_unavailable"

        holding_rows, holdings_asof_date, holdings_type = self.repository.holdings(
            canonical_id, effective_asof
        )
        exposure = calculate_top10_concentration(holding_rows)
        if exposure.reason:
            reasons["top10_concentration"] = exposure.reason
        if not holding_rows:
            reasons["top10"] = "holdings_unavailable"
        source_asof_dates["holdings"] = holdings_asof_date

        # ---- 份额与规模事实 ----
        share_rows = self.repository.share_history(canonical_id, effective_asof)
        estimated_aum = estimated_aum_date = estimated_aum_is_estimated = None
        if share_rows:
            latest_share = share_rows[-1]
            estimated_aum = latest_share.get("estimated_aum")
            estimated_aum_date = latest_share["trade_date"]
            estimated_aum_is_estimated = latest_share.get("is_estimated_aum")
        else:
            reasons["estimated_aum"] = "share_data_unavailable"
        source_asof_dates["share"] = estimated_aum_date

        # ---- 消费 flow_v2 ----
        flow_row = self.repository.flow_asof(canonical_id, effective_asof, current_flow_version())
        if flow_row:
            source_asof_dates["flow"] = flow_row.get("trade_date")
            share_change_20d = flow_row.get("share_change_20d")
            share_change_pct_20d = flow_row.get("share_change_pct_20d")
            estimated_subscription_20d = flow_row.get("estimated_net_subscription_20d")
            flow_version = flow_row.get("calculation_version") or current_flow_version()
        else:
            source_asof_dates["flow"] = None
            share_change_20d = None
            share_change_pct_20d = None
            estimated_subscription_20d = None
            flow_version = current_flow_version()

        if not share_rows:
            for metric_name in (
                "share_change_20d",
                "share_change_pct_20d",
                "estimated_net_subscription_20d",
            ):
                reasons[metric_name] = "share_data_unavailable"
        else:
            if share_change_20d is None:
                reasons["share_change_20d"] = "insufficient_history"
            if share_change_pct_20d is None:
                reasons["share_change_pct_20d"] = "insufficient_history"
            if estimated_subscription_20d is None:
                reasons["estimated_net_subscription_20d"] = (
                    "insufficient_history_or_nav_unavailable"
                )

        # ---- Tracking Error ----
        tracking_error_60d = None
        if tracking_index.id is None:
            reasons["tracking_error_60d"] = "tracking_index_unavailable"
        elif master and master.get("is_cross_border"):
            reasons["tracking_error_60d"] = "cross_border_alignment_not_supported"
        else:
            adj_nav_rows = self.repository.adjusted_nav_history(canonical_id, effective_asof)
            index_rows = self.repository.index_history(tracking_index.id, effective_asof)
            source_asof_dates["index"] = index_rows[-1]["trade_date"] if index_rows else None
            if adj_nav_rows and index_rows:
                source_asof_dates["nav"] = adj_nav_rows[-1]["nav_date"]
                nav_values = pd.Series(
                    [row["adjusted_nav"] for row in adj_nav_rows],
                    index=[row["nav_date"] for row in adj_nav_rows],
                )
                index_values = pd.Series(
                    [row["close"] for row in index_rows],
                    index=[row["trade_date"] for row in index_rows],
                )
                tracking_error_60d = tracking_error(nav_values, index_values, window=60)
            elif not adj_nav_rows:
                raw_nav_rows = self.repository.nav_history(canonical_id, effective_asof)
                source_asof_dates["nav"] = raw_nav_rows[-1]["nav_date"] if raw_nav_rows else None
                if raw_nav_rows and index_rows:
                    has_adj_col = any(r.get("adjusted_nav") is not None for r in raw_nav_rows)
                    if has_adj_col:
                        valid_pts = [r for r in raw_nav_rows if r.get("adjusted_nav") is not None]
                        if valid_pts:
                            nav_values = pd.Series(
                                [r["adjusted_nav"] for r in valid_pts],
                                index=[r["nav_date"] for r in valid_pts],
                            )
                            index_values = pd.Series(
                                [row["close"] for row in index_rows],
                                index=[row["trade_date"] for row in index_rows],
                            )
                            tracking_error_60d = tracking_error(nav_values, index_values, window=60)
                    else:
                        nav_vals = pd.Series(
                            [r["unit_nav"] for r in raw_nav_rows],
                            index=[r["nav_date"] for r in raw_nav_rows],
                        )
                        if has_unadjusted_jump(nav_vals):
                            tracking_error_60d = None
                            reasons["tracking_error_60d"] = "nav_not_adjusted_for_corporate_actions"
                        else:
                            index_values = pd.Series(
                                [row["close"] for row in index_rows],
                                index=[row["trade_date"] for row in index_rows],
                            )
                            tracking_error_60d = tracking_error(nav_vals, index_values, window=60)

            if tracking_error_60d is None and "tracking_error_60d" not in reasons:
                reasons["tracking_error_60d"] = "insufficient_aligned_history"

        reported_aum = master.get("reported_aum") if master else None
        reported_aum_date = master.get("reported_aum_date") if master else None
        if reported_aum is None:
            reasons["reported_aum"] = "reported_aum_unavailable"
        source_asof_dates["reported_aum"] = reported_aum_date

        quality = CoreMetricsQuality(
            status="PASS" if not reasons else "WARN",
            reasons=reasons,
            source_asof_dates=source_asof_dates,
        )
        return ETFCoreMetrics(
            security_id=canonical_id,
            asof_date=effective_asof,
            tracking_index=tracking_index,
            top10=exposure.holdings,
            top10_concentration=exposure.concentration,
            holdings_asof_date=holdings_asof_date,
            holdings_type=holdings_type,
            premium_discount_pct=premium_discount,
            turnover_amount=latest_quote.get("turnover_amount"),
            avg_turnover_amount_20d=avg_turnover,
            bid1=latest_quote.get("bid1"),
            ask1=latest_quote.get("ask1"),
            bid_ask_spread=bid_ask_spread,
            bid_ask_spread_pct=bid_ask_spread_pct,
            reported_aum=reported_aum,
            reported_aum_date=reported_aum_date,
            estimated_aum=estimated_aum,
            estimated_aum_date=estimated_aum_date,
            estimated_aum_is_estimated=estimated_aum_is_estimated,
            share_change_20d=share_change_20d,
            share_change_pct_20d=share_change_pct_20d,
            estimated_net_subscription_20d=estimated_subscription_20d,
            estimated_net_subscription_is_estimated=(
                True if estimated_subscription_20d is not None else None
            ),
            estimated_net_subscription_calculation_version=(
                flow_version if estimated_subscription_20d is not None else None
            ),
            market_return_20d=market_return_20d,
            market_return_60d=market_return_60d,
            max_drawdown_60d=max_drawdown_60d,
            tracking_error_60d=tracking_error_60d,
            quality=quality,
        )
