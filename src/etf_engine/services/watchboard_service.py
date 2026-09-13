"""看盘台应用服务：把三层状态、事实序列与篮子明细装配成一份 JSON。

界面只负责渲染：口径说明、覆盖度、缺口提示都由服务层给出，
避免前端各自拼口径。所有数字都能追到 ``core.*`` 的来源与 as-of 日期。
"""

from datetime import date

from etf_engine.domain.versions import FLOW_VERSION
from etf_engine.repositories.index_repository import IndexRepository
from etf_engine.repositories.market_repository import MarketRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.research.flow import cumulative_series
from etf_engine.research.market_pulse import (
    BROAD_BASE_INDEX_ALIASES,
    BROAD_BASE_INDICES,
    DEFAULT_BROAD_INDEX_ID,
    PULSE_VERSION,
    broad_index_ids,
    detect_transitions,
    quadrant_series,
    rolling_mean,
)
from etf_engine.sources.akshare.valuation import ALL_A_INDEX_ID

LAYER_LABELS = {
    "liquidity": "① 流动性",
    "volume": "② 量能",
    "etf": "③ 宽基 ETF",
}

#: 口径与缺口说明。界面上必须显示，不能只在文档里写。
KNOWN_GAPS = [
    "成交额口径为沪深两市股票，不含北交所、不含基金与债券。",
    "北向资金自 2024 年起上游不再披露实时净买入，本层不展示。",
    "深交所每日统计不披露换手率，深市换手率为 NULL。",
    "折溢价依赖 IOPV，只能从有快照的日期开始积累。",
]


class WatchboardService:
    def __init__(self, repository: MarketRepository | None = None):
        self.repository = repository or MarketRepository()

    def watchboard(self, asof_date: date | None = None, basket_limit: int = 50) -> dict:
        pulse_row = (
            self.repository.pulse_at(asof_date) if asof_date else self.repository.latest_pulse()
        )
        if pulse_row is None:
            return {
                "meta": {
                    "asof_date": None,
                    "quality": "EMPTY",
                    "calculation_version": PULSE_VERSION,
                    "hint": "本地还没有三层状态：先执行 etf sync-market 与 etf pulse",
                },
                "layers": [],
                "basket": [],
                "gaps": KNOWN_GAPS,
            }

        trade_date = pulse_row["trade_date"]
        basket = self.repository.basket_detail(broad_index_ids(), trade_date, limit=basket_limit)
        fund_issuance = self._fund_issuance()
        history_rows = self.repository.pulse_history(limit=250)

        return {
            "meta": {
                "asof_date": trade_date.isoformat(),
                "quality": "PASS",
                "calculation_version": pulse_row.get("calculation_version"),
                "overall_state": pulse_row.get("overall_state"),
                "strong_layers": pulse_row.get("overall_strong_layers"),
                "known_layers": pulse_row.get("overall_known_layers"),
                "quadrant_label": pulse_row.get("quadrant_label"),
                "turnover_scope": "沪深两市股票",
                "broad_index": {
                    "index_id": pulse_row.get("broad_index_id"),
                    "name": BROAD_BASE_INDICES.get(pulse_row.get("broad_index_id") or "", ""),
                    "position_pct_250d": pulse_row.get("broad_index_position_pct_250d"),
                },
            },
            "layers": self._layers(pulse_row, fund_issuance),
            "transitions": detect_transitions(history_rows),
            "turnover_series": self._with_moving_average(
                self.repository.turnover_series(limit=250)
            ),
            "margin_series": self.repository.margin_series(limit=250),
            "activity": self.repository.latest_activity(),
            "valuation": self.repository.latest_valuation(ALL_A_INDEX_ID),
            "index_positions": [
                self.repository.index_position(index_id) for index_id in sorted(BROAD_BASE_INDICES)
            ],
            "index_valuations": self._index_valuations(),
            "fund_issuance": fund_issuance,
            "quadrant_points": self._quadrant_points(),
            "freshness": self._freshness(trade_date),
            "basket": basket,
            "basket_flow": self._basket_flow(trade_date),
            "gaps": KNOWN_GAPS,
        }

    def history(self, limit: int = 120) -> list[dict]:
        return self.repository.pulse_history(limit=limit)

    @staticmethod
    def _basket_flow(asof: date) -> dict:
        """篮子成员按跟踪指数的逐日净申购与累积曲线（单位：元）。"""
        rows = MarketRepository().basket_flow_daily(broad_index_ids(), asof)

        # 按"指数身份"合并：中证 500 同时存在 000905（中证口径）与 399905
        # （新浪口径），它们是同一个指数，不能画成两条线。
        by_canonical: dict[str, dict[date, dict]] = {}
        for row in rows:
            canonical = BROAD_BASE_INDEX_ALIASES.get(row["index_id"], row["index_id"])
            bucket = by_canonical.setdefault(canonical, {})
            point = bucket.setdefault(
                row["trade_date"],
                {
                    "trade_date": row["trade_date"],
                    "daily_net_subscription": 0.0,
                    "contributor_count": 0,
                    "member_count": 0,
                },
            )
            if row["daily_net_subscription"] is not None:
                point["daily_net_subscription"] += float(row["daily_net_subscription"])
            point["contributor_count"] += row["contributor_count"]
            point["member_count"] += row["member_count"]

        series: list[dict] = []
        for index_id, points_by_date in by_canonical.items():
            points = [points_by_date[key] for key in sorted(points_by_date)]
            cumulative = cumulative_series(points)
            contributing = [point for point in points if point["contributor_count"] > 0]
            if not contributing:
                # 一只成员都没有日度数据（例如创业板指全是深市 ETF）：
                # 曲线画不出来就如实不画，不用 0 线冒充。
                continue
            latest = cumulative[-1]
            series.append(
                {
                    "index_id": index_id,
                    "index_name": BROAD_BASE_INDICES.get(index_id, index_id),
                    "member_count": points[0]["member_count"],
                    "contributor_count": contributing[-1]["contributor_count"],
                    "start_date": points[0]["trade_date"],
                    "end_date": points[-1]["trade_date"],
                    "cumulative_net_subscription": latest["cumulative_net_subscription"],
                    "points": [
                        {
                            "trade_date": point["trade_date"],
                            "daily_net_subscription": point["daily_net_subscription"],
                            "cumulative_net_subscription": point["cumulative_net_subscription"],
                            "contributor_count": point["contributor_count"],
                        }
                        for point in cumulative
                    ],
                }
            )

        series.sort(key=lambda item: item["index_id"])
        # 只报"按指数身份"后**真的画不出线**的指数：别名（如 399905）已经并入
        # 主代码（000905），不能把它算成缺数据；成员全是深市 ETF（没有日度份额）
        # 的指数也画不出线，同样要如实列出来。
        canonical_ids = sorted(
            {BROAD_BASE_INDEX_ALIASES.get(value, value) for value in broad_index_ids()}
        )
        rendered_ids = {item["index_id"] for item in series}
        return {
            "metric": "estimated_net_subscription_1d",
            "calculation_version": FLOW_VERSION,
            "unit": "元",
            "series": series,
            "window": {
                "start": min((item["start_date"] for item in series), default=None),
                "end": max((item["end_date"] for item in series), default=None),
            },
            "skipped_index_ids": [
                index_id for index_id in canonical_ids if index_id not in rendered_ids
            ],
            "skipped_index_names": [
                BROAD_BASE_INDICES.get(index_id, index_id)
                for index_id in canonical_ids
                if index_id not in rendered_ids
            ],
        }

    @staticmethod
    def _fund_issuance() -> dict:
        """新发基金月度规模（场外增量资金的代理指标）。

        "近 3 个月"只统计**完整月**：本月与上月往往还没录完，
        把不完整月算进对比会得出"发行冰点"的假信号。
        """
        monthly = MarketRepository().fund_issuance_monthly(months=18)
        series = [
            {
                "month": row["month_start"].strftime("%Y-%m"),
                "month_start": row["month_start"].date(),
                "fund_count": row["fund_count"],
                "raised_shares_total": row["raised_shares_total"],
                "missing_scale_count": row["missing_scale_count"],
            }
            for row in monthly
        ]
        current_month_start = date.today().replace(day=1)
        complete = [row for row in series if row["month_start"] < current_month_start]
        recent, previous = complete[-3:], complete[-6:-3]

        def total(rows: list[dict]) -> float | None:
            values = [
                row["raised_shares_total"] for row in rows if row["raised_shares_total"] is not None
            ]
            return sum(values) if values else None

        recent_total, previous_total = total(recent), total(previous)
        change_pct = (
            (recent_total / previous_total - 1) * 100 if recent_total and previous_total else None
        )
        return {
            "monthly": series,
            "recent_3m_raised_shares": recent_total,
            "recent_3m_fund_count": sum(row["fund_count"] for row in recent) or None,
            "previous_3m_raised_shares": previous_total,
            "change_pct": change_pct,
            "latest_complete_month": recent[-1]["month"] if recent else None,
            "current_month": current_month_start.strftime("%Y-%m"),
            "basis": "fund_new_found_em",
            "unit": "亿元（募集份额）",
        }

    @staticmethod
    def _quadrant_points() -> list[dict]:
        """量价四象限用的逐日散点（位置分位 × 量比）。"""
        close_series = (
            IndexRepository()
            .quote_history([DEFAULT_BROAD_INDEX_ID], limit=1500)
            .get(DEFAULT_BROAD_INDEX_ID, [])
        )
        turnover_series = MarketRepository().turnover_series(limit=250)
        return quadrant_series(close_series, turnover_series)

    def _freshness(self, asof: date) -> list[dict]:
        """各数据集 as-of 与滞后交易日数（界面用来显示"哪块数据旧了"）。"""
        rows = self.repository.dataset_freshness()
        calendar = TradingCalendarRepository().load()
        recent_days: list[date] = (
            calendar.trading_days_back(asof, 400) if calendar is not None else []
        )
        for row in rows:
            row_date = row.get("asof_date")
            if row_date is None or not recent_days:
                row["lag_trading_days"] = None
            elif row_date > recent_days[0]:
                # 比当前 as-of 还新：数据口径不一致，不猜原因，留空。
                row["lag_trading_days"] = None
            elif row_date in recent_days:
                row["lag_trading_days"] = recent_days.index(row_date)
            else:
                row["lag_trading_days"] = None
        return rows

    @staticmethod
    def _index_valuations() -> list[dict]:
        """宽基指数估值分位（月度 PE）。上游不覆盖的指数不会出现在这里。"""
        rows = MarketRepository().latest_index_valuations(broad_index_ids())
        for row in rows:
            row["index_name"] = BROAD_BASE_INDICES.get(row["index_id"], row["index_id"])
        return rows

    @staticmethod
    def _with_moving_average(series: list[dict], window: int = 20) -> list[dict]:
        """给成交额序列补 20 日均额（派生值，前端画均线用）。

        窗口不足的位置保持 NULL——前 19 个点没有均线，不会用当日值冒充。
        """
        averages = rolling_mean([row.get("turnover_amount_total") for row in series], window)
        for row, average in zip(series, averages, strict=True):
            row["turnover_amount_20d_avg"] = average
        return series

    @staticmethod
    def _layers(pulse_row: dict, fund_issuance: dict | None = None) -> list[dict]:
        """三层卡片的数据结构：状态 + 人话解释 + 关键事实。"""
        basket_size = pulse_row.get("broad_etf_basket_size")
        fund_issuance = fund_issuance or {}

        def pending_for(key: str) -> dict | None:
            """当日原始信号与确认状态不一致时，给出"待确认"提示。

            pulse_v2 的确认机制要求信号连续两天一致：所以"原始 ≠ 确认"
            就是**边际变化刚出现、还没被确认**的那一刻——比状态本身更值得看。
            """
            raw = pulse_row.get(f"{key}_raw_state")
            confirmed = pulse_row.get(f"{key}_state")
            if not raw or not confirmed or raw == confirmed:
                return None
            return {"from": confirmed, "to": raw}

        return [
            {
                "key": "liquidity",
                "label": LAYER_LABELS["liquidity"],
                "question": "市场有没有钱？",
                "state": pulse_row.get("liquidity_state"),
                "pending": pending_for("liquidity"),
                "score": pulse_row.get("liquidity_score"),
                "note": pulse_row.get("liquidity_note"),
                "facts": [
                    _fact("两融余额合计", pulse_row.get("margin_balance_total"), "money"),
                    _fact(
                        "5 日变化",
                        pulse_row.get("margin_balance_5d_change_pct"),
                        "pct",
                    ),
                    _fact(
                        "250 日分位",
                        pulse_row.get("margin_balance_position_pct_250d"),
                        "ratio",
                    ),
                    # 新发基金是"场外增量资金"的代理指标：只展示不打分——
                    # 发行冰点既可能是资金枯竭、也可能是底部区域的特征，
                    # 方向不稳定，塞进分数会改变当前 pulse_v2 的既有结论。
                    _fact(
                        "近 3 月新发基金",
                        fund_issuance.get("recent_3m_raised_shares"),
                        "yi_yuan",
                    ),
                ],
                "coverage": "沪深两市两融余额 + 新发基金成立规模（代理指标）",
                "unavailable": "北向资金（上游 2024 年后停止披露实时净买入）",
            },
            {
                "key": "volume",
                "label": LAYER_LABELS["volume"],
                "question": "钱动没动？",
                "state": pulse_row.get("volume_state"),
                "pending": pending_for("volume"),
                "score": pulse_row.get("volume_score"),
                "note": pulse_row.get("volume_note"),
                "facts": [
                    _fact("成交额合计", pulse_row.get("turnover_amount_total"), "money"),
                    _fact("20 日均额", pulse_row.get("turnover_amount_20d_avg"), "money"),
                    _fact("量比（5 日）", pulse_row.get("turnover_volume_ratio_5d"), "number"),
                    _fact(
                        "20 日均额分位",
                        pulse_row.get("turnover_amount_position_pct_250d"),
                        "ratio",
                    ),
                    # 换手率是水平值不是变化率：用 rate，避免被渲染成 "+1.39%"
                    _fact("沪市换手率", pulse_row.get("turnover_rate_pct"), "rate"),
                ],
                "coverage": "上交所 + 深交所每日概况",
                "unavailable": "深市换手率（上游不披露）",
            },
            {
                "key": "etf",
                "label": LAYER_LABELS["etf"],
                "question": "大钱进没进？",
                "state": pulse_row.get("etf_state"),
                "pending": pending_for("etf"),
                "score": pulse_row.get("etf_score"),
                "note": pulse_row.get("etf_note"),
                "facts": [
                    _fact(
                        "5 日估算净申购",
                        pulse_row.get("broad_etf_net_subscription_5d"),
                        "money",
                    ),
                    _fact(
                        "20 日估算净申购",
                        pulse_row.get("broad_etf_net_subscription_20d"),
                        "money",
                    ),
                    # 折溢价是比例（0.0026 = +0.26%），不是百分比数值：用 ratio
                    _fact("折溢价中位数", pulse_row.get("broad_etf_premium_median_pct"), "ratio"),
                    _fact(
                        f"{BROAD_BASE_INDICES.get(pulse_row.get('broad_index_id') or '', '')} "
                        "位置分位",
                        pulse_row.get("broad_index_position_pct_250d"),
                        "ratio",
                    ),
                ],
                "coverage": f"跟踪指数属于宽基篮子的 ETF，共 {basket_size or 0} 只",
                "unavailable": "折溢价历史（依赖 IOPV 快照，逐日积累）",
            },
        ]


def _fact(label: str, value, kind: str) -> dict:
    return {"label": label, "value": value, "kind": kind}
