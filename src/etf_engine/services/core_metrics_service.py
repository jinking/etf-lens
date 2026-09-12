from datetime import date

import pandas as pd

from etf_engine.domain.core_metrics import CoreMetricsQuality, ETFCoreMetrics, TrackingIndex
from etf_engine.domain.identifiers import SecurityId
from etf_engine.ingestion.normalizer import normalize_premium_discount
from etf_engine.repositories.core_metrics_repository import CoreMetricsRepository
from etf_engine.research.corporate_actions import has_unadjusted_jump
from etf_engine.research.exposure import calculate_top10_concentration
from etf_engine.research.flow import calculate_flow, share_change_pct
from etf_engine.research.liquidity import average_turnover_amount
from etf_engine.research.liquidity import bid_ask_spread as calculate_bid_ask_spread
from etf_engine.research.performance import simple_return
from etf_engine.research.risk import max_drawdown
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
        quote_frame = pd.DataFrame(quote_rows).set_index("trade_date")
        reasons: dict[str, str] = {}
        source_asof_dates: dict[str, date | None] = {"quote": effective_asof}

        premium_discount = latest_quote.get("premium_discount_pct_normalized")
        if premium_discount is None:
            premium_discount = normalize_premium_discount(
                latest_quote.get("close"), latest_quote.get("iopv")
            )
        if premium_discount is None:
            reasons["premium_discount_pct"] = "iopv_unavailable"

        avg_turnover = average_turnover_amount(quote_frame["turnover_amount"], 20)
        if latest_quote.get("turnover_amount") is None:
            reasons["turnover_amount"] = "turnover_amount_unavailable"
        if avg_turnover is None:
            reasons["avg_turnover_amount_20d"] = "insufficient_history"

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

        market_return_20d = simple_return(quote_frame["close"], 20)
        market_return_60d = simple_return(quote_frame["close"], 60)
        max_drawdown_60d = max_drawdown(quote_frame["close"], 60)
        # 未复权价格序列跨过除权/折算日时，收益与回撤指标不可用：
        # 必须给出真实原因，而不是笼统的"历史不足"。
        price_has_corporate_action = has_unadjusted_jump(quote_frame["close"])
        for metric_name, value in (
            ("market_return_20d", market_return_20d),
            ("market_return_60d", market_return_60d),
            ("max_drawdown_60d", max_drawdown_60d),
        ):
            if value is None:
                reasons[metric_name] = (
                    "corporate_action_in_window"
                    if price_has_corporate_action
                    else "insufficient_history"
                )

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

        share_rows = self.repository.share_history(canonical_id, effective_asof)
        estimated_aum = estimated_aum_date = estimated_aum_is_estimated = None
        share_change_20d = share_change_pct_20d = estimated_subscription_20d = None
        if share_rows:
            share_frame = pd.DataFrame(share_rows).set_index("trade_date")
            latest_share = share_rows[-1]
            estimated_aum = latest_share.get("estimated_aum")
            estimated_aum_date = latest_share["trade_date"]
            estimated_aum_is_estimated = latest_share.get("is_estimated_aum")
            flow = calculate_flow(share_frame["shares"], share_frame["nav"])
            share_change_20d = flow.share_change_20d
            share_change_pct_20d = share_change_pct(share_frame["shares"], 20)
            estimated_subscription_20d = flow.estimated_net_subscription_20d
            if share_change_20d is None:
                reasons["share_change_20d"] = "insufficient_history"
            if share_change_pct_20d is None:
                reasons["share_change_pct_20d"] = "insufficient_history"
            if estimated_subscription_20d is None:
                reasons["estimated_net_subscription_20d"] = (
                    "insufficient_history_or_nav_unavailable"
                )
        else:
            for metric_name in (
                "estimated_aum",
                "share_change_20d",
                "share_change_pct_20d",
                "estimated_net_subscription_20d",
            ):
                reasons[metric_name] = "share_data_unavailable"
        source_asof_dates["share"] = estimated_aum_date

        tracking_error_60d = None
        if tracking_index.id is None:
            reasons["tracking_error_60d"] = "tracking_index_unavailable"
        elif master and master.get("is_cross_border"):
            reasons["tracking_error_60d"] = "cross_border_alignment_not_supported"
        else:
            nav_rows = self.repository.nav_history(canonical_id, effective_asof)
            index_rows = self.repository.index_history(tracking_index.id, effective_asof)
            source_asof_dates["nav"] = nav_rows[-1]["nav_date"] if nav_rows else None
            source_asof_dates["index"] = index_rows[-1]["trade_date"] if index_rows else None
            if nav_rows and index_rows:
                nav_values = pd.Series(
                    [row["adjusted_nav"] or row["unit_nav"] for row in nav_rows],
                    index=[row["nav_date"] for row in nav_rows],
                )
                index_values = pd.Series(
                    [row["close"] for row in index_rows],
                    index=[row["trade_date"] for row in index_rows],
                )
                nav_has_corporate_action = has_unadjusted_jump(nav_values)
                tracking_error_60d = tracking_error(nav_values, index_values, window=60)
            else:
                nav_has_corporate_action = False
            if tracking_error_60d is None:
                reasons["tracking_error_60d"] = (
                    "nav_not_adjusted_for_corporate_actions"
                    if nav_has_corporate_action
                    else "insufficient_aligned_history"
                )

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
                "flow_v1" if estimated_subscription_20d is not None else None
            ),
            market_return_20d=market_return_20d,
            market_return_60d=market_return_60d,
            max_drawdown_60d=max_drawdown_60d,
            tracking_error_60d=tracking_error_60d,
            quality=quality,
        )
