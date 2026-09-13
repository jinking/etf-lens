"""把 ``pulse_v2`` 放回历史里做 **Historical Regime Validation**。

只读不写：读 ``mart.market_pulse_daily`` 的状态历史 + 宽基指数收盘价，
先按预先固定的 regime（自然年）切片，再对每段给出：

```text
days / UNKNOWN ratio / state distribution / switch count / average duration
forward 5/20/60 return / forward max drawdown
```

每个 ``(状态, 窗口)`` 同时给出 ``daily`` 与 ``transition`` 两套样本
（升级方案 §19）：前者每天都在数，后者只数"进入该状态的那一天"，
避免同一段连续状态被当成多个独立样本。

明确不做的事（升级方案 §15.2）：不为了让历史收益更好而自动调整阈值。
"""

from datetime import date
from pathlib import Path

import pandas as pd

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.versions import PULSE_VERSION
from etf_engine.research.market_pulse import DEFAULT_BROAD_INDEX_ID, OverallState
from etf_engine.research.regime_validation import build_report, render_markdown

DEFAULT_DOC_PATH = Path("docs/REGIME_VALIDATION.md")

#: 覆盖目标（升级方案 §17）：最低 3 年，理想 5 年；由数据可得性决定。
MIN_COVERAGE_YEARS = 3
IDEAL_COVERAGE_YEARS = 5


def _pulse_history(asof: date | None = None) -> pd.DataFrame:
    with connect(settings.database_path) as con:
        rows = con.execute(
            """
            SELECT trade_date, overall_state, liquidity_state, volume_state, etf_state,
                   broad_index_id, calculation_version
            FROM mart.market_pulse_daily
            WHERE (? IS NULL OR trade_date <= ?)
            ORDER BY trade_date
            """,
            [asof, asof],
        ).fetchall()
        columns = [c[0] for c in con.description]
    return pd.DataFrame(rows, columns=columns)


def _index_close(index_id: str) -> pd.Series:
    with connect(settings.database_path) as con:
        rows = con.execute(
            """
            SELECT trade_date, close FROM core.index_quote_daily
            WHERE index_id = ? ORDER BY trade_date
            """,
            [index_id],
        ).fetchall()
    if not rows:
        return pd.Series(dtype="float64")
    return pd.Series([row[1] for row in rows], index=[row[0] for row in rows])


def _coverage_years(dates: list[date]) -> float:
    if not dates:
        return 0.0
    return (max(dates) - min(dates)).days / 365.25


def validate_pulse(
    asof: date | None = None,
    *,
    write_doc: bool = False,
    doc_path: Path | None = None,
) -> dict:
    frame = _pulse_history(asof)
    if frame.empty:
        return {"status": "SKIPPED", "reason": "没有状态历史，先跑 etf pulse / backfill-pulse"}

    versions = sorted(set(frame["calculation_version"].dropna()))
    index_id = (
        str(frame["broad_index_id"].dropna().iloc[-1])
        if frame["broad_index_id"].notna().any()
        else DEFAULT_BROAD_INDEX_ID
    )
    price = _index_close(index_id)

    # 与指数交易日对齐后再算后续收益：状态有、指数没有的日子不能前向填充。
    aligned = frame[frame["trade_date"].isin(price.index)]
    trade_dates = [pd.Timestamp(value).date() for value in aligned["trade_date"]]
    states = [str(value) for value in aligned["overall_state"].tolist()]
    coverage = _coverage_years(trade_dates)

    notes = [
        f"状态来源：`mart.market_pulse_daily`，口径 {', '.join(versions) or '未知'}。",
        f"后续收益基准：指数 `{index_id}` 的收盘价（与状态同源、不额外选取有利区间）。",
        f"UNKNOWN（{OverallState.UNKNOWN.value}）不计入后续收益统计，但计入覆盖与占比。",
        "样本分两套：`daily` 每天都算一个样本（分布描述）；"
        "`transition` 只算状态首次进入的那一天（首日 + 每次切换当天），"
        "避免连续多日的高度重叠样本被当成独立事件。",
        "观察窗口允许跨出 regime 边界（例如 12 月末可以看到次年 1 月），"
        "否则每年最后 5/20/60 个交易日的样本会被系统性丢掉。",
        "回撤计算口径：前向真实最大回撤（`window = [start] + forward`，"
        "`window / running_peak - 1` 的最小值，V2.1.1 修正，不与起点不利变动 MAE 混淆）。",
        "历史回放是「用今天存下的事实按同一条规则重算」，不是当时写下的快照；"
        "篮子成员按当前跟踪关系取，成员变动未回溯；折溢价依赖当日 IOPV 快照，"
        "历史上大多为 NULL。这些边界都会让早期状态的可信度低于最近一年。",
    ]
    if len(versions) != 1:
        notes.append("警告：状态历史里混了多个口径版本，跨版本比较没有意义。")
    if coverage < MIN_COVERAGE_YEARS:
        notes.append(
            f"警告：当前覆盖仅 {coverage:.1f} 年，低于最低目标 {MIN_COVERAGE_YEARS} 年"
            "（升级方案 §17）；需要先 `etf sync-market` 回补成交额与两融后重跑回放。"
        )

    report = build_report(
        states=states,
        index_close=price.loc[[day for day in aligned["trade_date"]]],
        # 这里统计的是 ``overall_state``，它的"数据不足"是 OverallState.UNKNOWN，
        # 不是 LayerState.UNKNOWN（"UNKNOWN"）。用错标签会把数据不足当成一个真实状态
        # 参与后续收益统计，同时把 UNKNOWN 占比报成 0%。
        unknown_state=OverallState.UNKNOWN.value,
        dates=trade_dates,
        notes=notes,
    )

    context = [
        f"> 规则版本：`{PULSE_VERSION}` ｜ 生成时间："
        f"{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        ">",
        f"> 覆盖区间：{trade_dates[0] if trade_dates else '—'} ~ "
        f"{trade_dates[-1] if trade_dates else '—'}（约 {coverage:.1f} 年，"
        f"最低目标 {MIN_COVERAGE_YEARS} 年 / 理想 {IDEAL_COVERAGE_YEARS} 年）",
        ">",
        "> 本文由 `etf validate-pulse --write-doc` 生成，可随时重跑复现。",
        "",
    ]

    markdown = render_markdown(
        report, title=f"pulse_v2 历史 regime 验证（{PULSE_VERSION}）", context=context
    )

    target = doc_path or DEFAULT_DOC_PATH
    written = False
    if write_doc:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        written = True

    return {
        "status": "SUCCESS",
        "days": report.days,
        "unknown_ratio": report.unknown_ratio,
        "switch_count": report.switch_count,
        "coverage_years": round(coverage, 2),
        "coverage_start": trade_dates[0].isoformat() if trade_dates else None,
        "coverage_end": trade_dates[-1].isoformat() if trade_dates else None,
        "states": [
            {
                "state": item.state,
                "days": item.days,
                "share": item.share,
                "average_duration": item.average_duration,
            }
            for item in report.states
        ],
        "daily_sample_count": sum(item.daily.sample_count for item in report.outcomes),
        "transition_sample_count": sum(item.transition.sample_count for item in report.outcomes),
        "regimes": [
            {
                "label": regime.label,
                "days": regime.days,
                "switch_count": regime.switch_count,
                "unknown_ratio": regime.unknown_ratio,
                "daily_sample_count": sum(item.daily.sample_count for item in regime.outcomes),
                "transition_sample_count": sum(
                    item.transition.sample_count for item in regime.outcomes
                ),
            }
            for regime in report.regimes
        ],
        "benchmark_index": index_id,
        "doc_path": str(target) if written else None,
        "markdown": markdown if not written else None,
    }
