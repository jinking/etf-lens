"""三层看盘规则引擎（``pulse_v2``）。

纯函数、无 I/O、无网络：输入是已经落到 core/mart 的事实序列，输出是状态标签。
规则与阈值写在 :data:`PULSE_VERSION` 对应的常量里，改口径必须升版本号。

v2 相对 v1 的唯一变化是**确认机制**：某层的原始信号必须连续
``CONFIRM_DAYS`` 天落在新状态才真的切过去（v1 实测量能层 250 天切换 77 次，
平均持续 3.2 天，那是噪音不是状态）。原始信号与确认状态都落库。

边界说明（对应 docs/WATCHBOARD.md 第 2 节）：

* 这是确定性规则引擎，不是观点，不预测涨跌；
* 数据不足时输出 ``UNKNOWN``，不硬凑结论；
* 折溢价、量价四象限只做标签，不进分数，避免制造虚假精度。
"""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from statistics import mean

PULSE_VERSION = "pulse_v2"

#: 状态确认所需的天数：原始信号必须连续这么多天落在新状态，才真的切过去。
#: v1 的阈值偏紧，实测量能层 250 天切换 77 次（平均持续 3.2 天），
#: 综合结论 3.6 天变一次——那是噪音不是状态。确认 2 天后切换次数减半，
#: 代价是滞后 1 天，符合"状态判断器"而不是"择时信号"的定位。
CONFIRM_DAYS = 2

#: 判定阈值（改这些数字必须同时升 PULSE_VERSION）。
MARGIN_CHANGE_STRONG_PCT = 0.5
VOLUME_RATIO_STRONG = 1.1
VOLUME_RATIO_WEAK = 0.9
POSITION_HIGH = 0.6
POSITION_LOW = 0.4
#: 分位窗口与最小样本量。样本不足时该子信号为 None，而不是硬算。
POSITION_WINDOW = 250
POSITION_MIN_SAMPLES = 60
#: 四象限的"低位/高位"分界（展示标签用的阈值，与打分阈值分开）。
QUADRANT_LOW = 0.35
QUADRANT_HIGH = 0.65


class LayerState(StrEnum):
    STRONG = "STRONG"
    NEUTRAL = "NEUTRAL"
    WEAK = "WEAK"
    UNKNOWN = "UNKNOWN"


class OverallState(StrEnum):
    BULLISH = "偏多"
    NEUTRAL = "中性观望"
    DEFENSIVE = "防守"
    UNKNOWN = "数据不足"


#: 宽基 ETF 篮子的判定口径：跟踪指数在这个集合里的 ETF 才算篮子成员。
#: 用基金披露的跟踪指数（事实），不用名称模糊匹配。
BROAD_BASE_INDICES: dict[str, str] = {
    "000016": "上证50",
    "000300": "沪深300",
    "000510": "中证A500",
    "000905": "中证500",
    "000852": "中证1000",
    "000688": "科创50",
    "399006": "创业板指",
}

#: 同一个指数的不同目录口径：中证代码 vs 新浪符号码。
#: 实测同一只中证 500 ETF 会映射到 399905（新浪口径）而不是 000905（中证口径），
#: 只按单一代码取篮子会把它漏掉。此处按**指数身份**取并集，别名方向固定为
#: 别名 → 主代码，主代码是 docs 与 UI 上展示的那个。
BROAD_BASE_INDEX_ALIASES: dict[str, str] = {
    "399905": "000905",
}


def broad_index_ids() -> list[str]:
    """篮子的取数口径：主代码 + 别名（去重后排序）。"""
    return sorted(set(BROAD_BASE_INDICES) | set(BROAD_BASE_INDEX_ALIASES))


#: 代表 A 股整体的宽基指数，用于位置分位与量价四象限。
DEFAULT_BROAD_INDEX_ID = "000300"

LAYER_LABELS = {
    "liquidity": "流动性",
    "volume": "量能",
    "etf": "宽基 ETF",
}


@dataclass(frozen=True, slots=True)
class LayerResult:
    state: LayerState
    score: int
    note: str
    metrics: dict = field(default_factory=dict)


def _valid(values) -> list[float | None]:
    return [None if value is None else float(value) for value in values]


def _clean(values) -> list[float]:
    return [float(value) for value in values if value is not None]


def change_pct(values: list[float | None], periods: int) -> float | None:
    """最近 ``periods`` 个有观测交易日的涨跌率（%）。

    上游缺披露的日期不插值，窗口因此可能跨越更长自然日——
    与 ``mart.etf_flow_daily`` 的口径保持一致。
    """
    series = _clean(values)
    if len(series) < periods + 1:
        return None
    base = series[-(periods + 1)]
    if base == 0:
        return None
    return (series[-1] / base - 1) * 100


def percentile_rank(
    values: list[float | None],
    *,
    window: int = POSITION_WINDOW,
    min_samples: int = POSITION_MIN_SAMPLES,
) -> float | None:
    """最新值在窗口内的分位（0~1）；样本不足返回 None。"""
    series = _clean(values)[-window:]
    if len(series) < min_samples:
        return None
    current = series[-1]
    below = sum(1 for value in series if value < current)
    equal = sum(1 for value in series if value == current)
    # 并列值取中点：全是同一个数时不会被算成 0 或 1。
    return (below + equal / 2) / len(series)


def rolling_mean(values: list[float | None], window: int) -> list[float | None]:
    """滚动均值；窗口内有效样本不足时为 None。"""
    series = _valid(values)
    result: list[float | None] = []
    for index in range(len(series)):
        if index + 1 < window:
            result.append(None)
            continue
        chunk = _clean(series[index + 1 - window : index + 1])
        result.append(mean(chunk) if len(chunk) == window else None)
    return result


def _score_to_state(score: int) -> LayerState:
    if score >= 1:
        return LayerState.STRONG
    if score <= -1:
        return LayerState.WEAK
    return LayerState.NEUTRAL


def evaluate_liquidity(margin_series: list[dict]) -> LayerResult:
    """第一层：流动性（有没有钱）。

    主信号是两融余额的边际变化（5 日），250 日分位只做位置参照——
    文档 1.3 的要点是"看边际变化，不看绝对水平"。
    """
    balances = _valid([row.get("margin_balance_total") for row in margin_series])
    asof = margin_series[-1].get("trade_date") if margin_series else None

    if len(_clean(balances)) < 6:
        return LayerResult(
            LayerState.UNKNOWN,
            0,
            f"两融余额历史不足（{len(_clean(balances))} 个交易日，至少需要 6 个）",
            {"margin_balance_total": balances[-1] if balances else None},
        )

    change_5d = change_pct(balances, 5)
    position = percentile_rank(balances)

    score = 0
    parts: list[str] = []
    if change_5d is None:
        parts.append("5 日变化率不可得")
    elif change_5d > MARGIN_CHANGE_STRONG_PCT:
        score += 1
        parts.append(f"两融余额 5 日 {change_5d:+.2f}%，杠杆资金回升")
    elif change_5d < -MARGIN_CHANGE_STRONG_PCT:
        score -= 1
        parts.append(f"两融余额 5 日 {change_5d:+.2f}%，杠杆资金撤离")
    else:
        parts.append(f"两融余额 5 日 {change_5d:+.2f}%，横盘")

    if position is None:
        parts.append("250 日分位样本不足")
    elif position >= POSITION_HIGH:
        score += 1
        parts.append(f"余额处于 250 日 {position * 100:.0f}% 分位，偏高位")
    elif position <= POSITION_LOW:
        score -= 1
        parts.append(f"余额处于 250 日 {position * 100:.0f}% 分位，偏低位")
    else:
        parts.append(f"余额处于 250 日 {position * 100:.0f}% 分位")

    if change_5d is None and position is None:
        return LayerResult(LayerState.UNKNOWN, 0, "；".join(parts))

    return LayerResult(
        _score_to_state(score),
        score,
        "；".join(parts),
        {
            "margin_balance_total": balances[-1],
            "margin_balance_5d_change_pct": change_5d,
            "margin_balance_position_pct_250d": position,
            "asof_date": asof,
        },
    )


def evaluate_volume(turnover_series: list[dict]) -> LayerResult:
    """第二层：量能（钱动没动）。

    量比是派生指标：当日成交额 ÷ 前 5 个交易日均值（不含当日）。
    """
    amounts = _valid([row.get("turnover_amount_total") for row in turnover_series])
    asof = turnover_series[-1].get("trade_date") if turnover_series else None

    if len(_clean(amounts)) < 6:
        return LayerResult(
            LayerState.UNKNOWN,
            0,
            f"成交额历史不足（{len(_clean(amounts))} 个交易日，至少需要 6 个）",
            {"turnover_amount_total": amounts[-1] if amounts else None},
        )

    trailing = [value for value in amounts[:-1] if value is not None][-5:]
    latest = amounts[-1]
    volume_ratio = None
    if len(trailing) == 5 and latest is not None and mean(trailing) != 0:
        volume_ratio = latest / mean(trailing)

    avg20 = rolling_mean(amounts, 20)
    avg20_position = percentile_rank(avg20)

    score = 0
    parts: list[str] = []
    if volume_ratio is None or latest is None:
        parts.append("量比不可得")
    elif volume_ratio >= VOLUME_RATIO_STRONG:
        score += 1
        parts.append(f"成交额 {latest / 1e8:.0f} 亿，量比 {volume_ratio:.2f}，放量")
    elif volume_ratio <= VOLUME_RATIO_WEAK:
        score -= 1
        parts.append(f"成交额 {latest / 1e8:.0f} 亿，量比 {volume_ratio:.2f}，缩量")
    else:
        parts.append(f"成交额 {latest / 1e8:.0f} 亿，量比 {volume_ratio:.2f}，平量")

    if avg20_position is None:
        parts.append("20 日均额 250 日分位样本不足")
    elif avg20_position >= POSITION_HIGH:
        score += 1
        parts.append(f"20 日均额处于 250 日 {avg20_position * 100:.0f}% 分位，活跃")
    elif avg20_position <= POSITION_LOW:
        score -= 1
        parts.append(f"20 日均额处于 250 日 {avg20_position * 100:.0f}% 分位，地量区")
    else:
        parts.append(f"20 日均额处于 250 日 {avg20_position * 100:.0f}% 分位")

    if volume_ratio is None and avg20_position is None:
        # 状态不可判定，但已算出的量能事实照常返回（UI 仍要显示当日成交额）。
        return LayerResult(
            LayerState.UNKNOWN,
            0,
            "；".join(parts),
            {
                "turnover_amount_total": latest,
                "turnover_amount_5d_avg": mean(trailing) if len(trailing) == 5 else None,
                "turnover_amount_20d_avg": avg20[-1],
                "turnover_volume_ratio_5d": volume_ratio,
                "turnover_amount_position_pct_250d": avg20_position,
                "turnover_rate_pct": turnover_series[-1].get("turnover_rate_pct"),
                "asof_date": asof,
            },
        )

    return LayerResult(
        _score_to_state(score),
        score,
        "；".join(parts),
        {
            "turnover_amount_total": latest,
            "turnover_amount_5d_avg": mean(trailing) if len(trailing) == 5 else None,
            "turnover_amount_20d_avg": avg20[-1],
            "turnover_volume_ratio_5d": volume_ratio,
            "turnover_amount_position_pct_250d": avg20_position,
            "turnover_rate_pct": turnover_series[-1].get("turnover_rate_pct"),
            "asof_date": asof,
        },
    )


def evaluate_etf_basket(basket: dict) -> LayerResult:
    """第三层：宽基 ETF（大钱进没进）。

    只用份额变化推出的估算净申购方向打分；折溢价与指数位置只做展示。
    """
    net_5d = basket.get("net_subscription_5d")
    net_20d = basket.get("net_subscription_20d")
    basket_size = basket.get("basket_size") or 0

    if not basket_size:
        return LayerResult(
            LayerState.UNKNOWN,
            0,
            "宽基 ETF 篮子为空：先跑 etf sync-index-map 补齐跟踪指数映射",
        )

    if net_5d is None and net_20d is None:
        return LayerResult(
            LayerState.UNKNOWN,
            0,
            f"篮子 {basket_size} 只 ETF，但净申购窗口不可得",
            {"basket_size": basket_size},
        )

    score = sum(1 if value > 0 else -1 for value in (net_5d, net_20d) if value is not None)
    parts: list[str] = []
    parts.append(
        "5 日估算净申购不可得" if net_5d is None else f"5 日估算净申购 {net_5d / 1e8:+.1f} 亿"
    )
    parts.append(
        "20 日估算净申购不可得" if net_20d is None else f"20 日估算净申购 {net_20d / 1e8:+.1f} 亿"
    )
    parts.append(f"篮子 {basket_size} 只")

    # 折溢价只展示、不打分：文档自己就说"持续溢价 = 过热、持续折价 = 抛压重"，
    # 方向不稳定，塞进分数会制造虚假精度。
    premium = basket.get("premium_median_pct")
    if premium is not None:
        parts.append(f"折溢价中位数 {premium * 100:+.2f}%")

    return LayerResult(
        _score_to_state(score),
        score,
        "；".join(parts),
        {
            "basket_size": basket_size,
            "net_subscription_5d": net_5d,
            "net_subscription_20d": net_20d,
            "premium_median_pct": premium,
        },
    )


def quadrant_label(position_pct_250d: float | None, volume_ratio_5d: float | None) -> str | None:
    """量价四象限标签（文档 2.4）。只做展示，不参与打分。"""
    if position_pct_250d is None or volume_ratio_5d is None:
        return None

    if position_pct_250d >= QUADRANT_HIGH:
        zone = "high"
    elif position_pct_250d <= QUADRANT_LOW:
        zone = "low"
    else:
        zone = "mid"

    if volume_ratio_5d >= VOLUME_RATIO_STRONG:
        flow = "expand"
    elif volume_ratio_5d <= VOLUME_RATIO_WEAK:
        flow = "shrink"
    else:
        flow = "flat"

    labels = {
        ("low", "expand"): "低位放量：吸筹/启动，重点跟踪",
        ("low", "shrink"): "低位缩量：阴跌寻底或筑底，等待方向",
        ("high", "expand"): "高位放量：出货/赶顶，高度警惕",
        ("high", "shrink"): "高位缩量：惜售延续或量价背离，谨慎",
    }
    mapped = labels.get((zone, flow))
    if mapped:
        return mapped

    zone_text = {"low": "低位", "mid": "中位", "high": "高位"}[zone]
    flow_text = {"expand": "放量", "shrink": "缩量", "flat": "平量"}[flow]
    return f"{zone_text}{flow_text}：信号不明确"


def quadrant_series(
    close_series: list[dict],
    turnover_series: list[dict],
    *,
    window: int = POSITION_WINDOW,
) -> list[dict]:
    """逐日算出「位置分位 × 量比」，供量价四象限散点图使用。

    两个输入都是事实序列（指数收盘价、沪深合计成交额），按日期取交集：
    只有两边都有观测的交易日才产出点，缺失不插值。
    """
    closes_by_date = {
        row["trade_date"]: row["close"]
        for row in close_series
        if row.get("close") is not None
    }
    ordered_dates = sorted(closes_by_date)
    amounts = [row.get("turnover_amount_total") for row in turnover_series]

    points: list[dict] = []
    for index, row in enumerate(turnover_series):
        day = row.get("trade_date")
        amount = amounts[index]
        if day is None or amount is None or day not in closes_by_date:
            continue

        # 位置分位只用"截至当日"的收盘价，避免用未来数据。
        past_closes = [closes_by_date[value] for value in ordered_dates if value <= day]
        position = percentile_rank(past_closes, window=window)

        # 量比 = 当日成交额 ÷ 前 5 个有观测交易日均值（不含当日）。
        trailing = [value for value in amounts[:index] if value is not None][-5:]
        volume_ratio = None
        if len(trailing) == 5 and mean(trailing) != 0:
            volume_ratio = amount / mean(trailing)

        if position is None or volume_ratio is None:
            continue
        points.append(
            {
                "trade_date": day,
                "position_pct_250d": position,
                "volume_ratio_5d": volume_ratio,
                "turnover_amount_total": amount,
                "quadrant_label": quadrant_label(position, volume_ratio),
            }
        )
    return points


def overall_state(states: dict[str, LayerState]) -> tuple[OverallState, int, int]:
    """文档 4.2：达成 STRONG 的层数 >=2 偏多、=1 中性观望、=0 防守。

    已知层不足两层时输出"数据不足"——宁可不说，也不拿一层数据下结论。
    """
    known = [state for state in states.values() if state != LayerState.UNKNOWN]
    strong = sum(1 for state in known if state == LayerState.STRONG)
    if len(known) < 2:
        return OverallState.UNKNOWN, strong, len(known)
    if strong >= 2:
        return OverallState.BULLISH, strong, len(known)
    if strong == 1:
        return OverallState.NEUTRAL, strong, len(known)
    return OverallState.DEFENSIVE, strong, len(known)


#: 状态切换事件的层标签与"意义"归类。
LAYER_NOTE_KEYS = {
    "liquidity": "liquidity_note",
    "volume": "volume_note",
    "etf": "etf_note",
}
LAYER_STATE_KEYS = {
    "liquidity": "liquidity_state",
    "volume": "volume_state",
    "etf": "etf_state",
}

#: 单层转向的意义：文档的传导链是"流动性先行 → 量能确认 → ETF 验证"。
LAYER_SIGNIFICANCE = {
    "liquidity": "资金先行信号",
    "volume": "量能确认/背离",
    "etf": "大钱动作",
}


def confirm_states(
    raw_states: list[str],
    *,
    confirm_days: int = CONFIRM_DAYS,
) -> list[str]:
    """把逐日原始信号变成"确认状态"（pulse_v2 的确认机制）。

    规则：原始信号必须**连续 ``confirm_days`` 天**落在新状态才切换过去，
    否则维持上一个确认状态。首日没有历史，直接采用当日原始信号。

    ``UNKNOWN``（数据缺失）不参与确认，立即生效——数据开始覆盖或中断
    是口径事件，不是市场状态，拖延它只会让缺口看起来像"还维持着旧状态"。
    """
    confirmed: list[str] = []
    current: str | None = None
    pending: str | None = None
    pending_days = 0

    for raw in raw_states:
        if current is None:
            current = raw
        elif raw == LayerState.UNKNOWN.value or current == LayerState.UNKNOWN.value:
            current = raw
            pending, pending_days = None, 0
        elif raw == current:
            pending, pending_days = None, 0
        else:
            if pending == raw:
                pending_days += 1
            else:
                pending, pending_days = raw, 1
            if pending_days >= confirm_days:
                current = raw
                pending, pending_days = None, 0
        confirmed.append(current)
    return confirmed


def step_confirmed(
    *,
    confirmed_prev: str | None,
    raw_prev: str | None,
    raw_today: str,
    confirm_days: int = CONFIRM_DAYS,
) -> str:
    """日更用的单步确认：只需要上一行的确认状态与原始信号。

    规则与 :func:`confirm_states` 完全一致（有单测逐条比对），只是不需要
    整段历史。仅适用于 ``confirm_days <= 2``——需要更长确认窗口时，
    请用 ``confirm_states`` 对整段序列重放。
    """
    if confirm_days > 2:
        raise ValueError("step_confirmed 只支持 confirm_days <= 2，请改用 confirm_states")
    unknown = LayerState.UNKNOWN.value
    if confirmed_prev is None:
        return raw_today
    if raw_today == unknown or confirmed_prev == unknown:
        return raw_today
    if raw_today == confirmed_prev:
        return confirmed_prev
    # 原始信号连续两天一致 → 确认切换
    if raw_prev is not None and raw_today == raw_prev:
        return raw_today
    return confirmed_prev


def detect_transitions(rows: list[dict]) -> list[dict]:
    """从状态序列里找出"边际变化"发生的那些日子。

    文档 1.3 的核心是"看边际变化，不看绝对水平"，所以真正值得盯的不是某天的
    状态值，而是**哪天变了、是谁先变的**。

    两类事件必须分开，否则会把数据问题当成市场信号：

    * ``market``：变化前后的层状态都是已知的，是真正的状态切换；
    * ``coverage``：有一端是 ``UNKNOWN``（例如宽基 ETF 层在申赎历史回填之前
      没有数据），那是**数据覆盖开始/中断**，不是市场事件。

    ``leading_layer`` 只在"当天恰好只有一层变化"时给出；多层同时变化记为共振。
    """
    events: list[dict] = []
    for previous, current in zip(rows, rows[1:], strict=False):
        changed: list[dict] = []
        involves_unknown = False
        for key, state_key in LAYER_STATE_KEYS.items():
            before = previous.get(state_key) or LayerState.UNKNOWN.value
            after = current.get(state_key) or LayerState.UNKNOWN.value
            if before == after:
                continue
            if LayerState.UNKNOWN.value in {before, after}:
                involves_unknown = True
            changed.append(
                {
                    "key": key,
                    "label": LAYER_LABELS[key],
                    "from": before,
                    "to": after,
                    "note": current.get(LAYER_NOTE_KEYS[key]),
                }
            )

        before_overall = previous.get("overall_state")
        after_overall = current.get("overall_state")
        overall_changed = before_overall != after_overall
        if not changed and not overall_changed:
            continue

        leading = changed[0]["key"] if len(changed) == 1 else None
        if involves_unknown:
            significance = "数据开始覆盖/中断"
        elif leading is not None:
            significance = LAYER_SIGNIFICANCE.get(leading, "单层变化")
        else:
            significance = "多层共振转向"

        events.append(
            {
                "trade_date": current.get("trade_date"),
                "overall_changed": overall_changed,
                "from_state": before_overall,
                "to_state": after_overall,
                "changed_layers": changed,
                "leading_layer": leading,
                "kind": "coverage" if involves_unknown else "market",
                "significance": significance,
            }
        )
    return events


def build_pulse_row(
    *,
    trade_date: date,
    liquidity: LayerResult,
    volume: LayerResult,
    etf: LayerResult,
    basket: dict,
    broad_index_id: str = DEFAULT_BROAD_INDEX_ID,
    broad_index_position_pct_250d: float | None = None,
    activity: dict | None = None,
    calculated_at=None,
    confirmed_states: dict[str, str] | None = None,
) -> dict:
    """把三层结果装配成 ``mart.market_pulse_daily`` 的一行。

    ``liquidity/volume/etf`` 传进来的是**当日原始信号**；``confirmed_states``
    是经确认机制处理后的状态（pulse_v2）。综合结论按**确认后的各层**重算，
    原始信号同时落库——"原始 ≠ 确认"就是"边际变化刚出现、还没被确认"。
    """
    raw_states = {
        "liquidity": liquidity.state.value,
        "volume": volume.state.value,
        "etf": etf.state.value,
    }
    states = {**raw_states, **(confirmed_states or {})}
    overall, strong_layers, known_layers = overall_state(
        {key: LayerState(value) for key, value in states.items()}
    )
    activity = activity or {}
    return {
        "trade_date": trade_date,
        "margin_balance_total": liquidity.metrics.get("margin_balance_total"),
        "margin_balance_5d_change_pct": liquidity.metrics.get("margin_balance_5d_change_pct"),
        "margin_balance_position_pct_250d": liquidity.metrics.get(
            "margin_balance_position_pct_250d"
        ),
        "liquidity_state": states["liquidity"],
        "liquidity_raw_state": raw_states["liquidity"],
        "liquidity_score": liquidity.score,
        "liquidity_note": liquidity.note,
        "turnover_amount_total": volume.metrics.get("turnover_amount_total"),
        "turnover_amount_5d_avg": volume.metrics.get("turnover_amount_5d_avg"),
        "turnover_amount_20d_avg": volume.metrics.get("turnover_amount_20d_avg"),
        "turnover_volume_ratio_5d": volume.metrics.get("turnover_volume_ratio_5d"),
        "turnover_amount_position_pct_250d": volume.metrics.get(
            "turnover_amount_position_pct_250d"
        ),
        "turnover_rate_pct": volume.metrics.get("turnover_rate_pct"),
        "rising_count": activity.get("rising_count"),
        "falling_count": activity.get("falling_count"),
        "limit_up_count": activity.get("limit_up_count"),
        "limit_down_count": activity.get("limit_down_count"),
        "volume_state": states["volume"],
        "volume_raw_state": raw_states["volume"],
        "volume_score": volume.score,
        "volume_note": volume.note,
        "broad_etf_basket_size": basket.get("basket_size"),
        "broad_etf_net_subscription_5d": basket.get("net_subscription_5d"),
        "broad_etf_net_subscription_20d": basket.get("net_subscription_20d"),
        "broad_etf_premium_median_pct": basket.get("premium_median_pct"),
        "broad_index_id": broad_index_id,
        "broad_index_position_pct_250d": broad_index_position_pct_250d,
        "etf_state": states["etf"],
        "etf_raw_state": raw_states["etf"],
        "etf_score": etf.score,
        "etf_note": etf.note,
        "overall_state": overall.value,
        "overall_strong_layers": strong_layers,
        "overall_known_layers": known_layers,
        "quadrant_label": quadrant_label(
            broad_index_position_pct_250d, volume.metrics.get("turnover_volume_ratio_5d")
        ),
        "calculation_version": PULSE_VERSION,
        "calculated_at": calculated_at,
    }
