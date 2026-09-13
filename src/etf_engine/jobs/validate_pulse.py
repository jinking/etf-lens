"""把 ``pulse_v2`` 放到历史里验证，并产出可复现的验证报告。

只读不写：读 ``mart.market_pulse_daily`` 的状态历史 + 宽基指数收盘价，
按年切片做 walk-forward 统计，渲染成 ``docs/PULSE_VALIDATION.md``。

明确不做的事（升级方案 §6.3）：不为了让历史收益更好而自动调整阈值。
"""

from datetime import date
from pathlib import Path

import pandas as pd

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.versions import PULSE_VERSION
from etf_engine.research.market_pulse import DEFAULT_BROAD_INDEX_ID, LayerState
from etf_engine.research.walk_forward import build_report, render_markdown

DEFAULT_DOC_PATH = Path("docs/PULSE_VALIDATION.md")


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

    notes = [
        f"状态来源：`mart.market_pulse_daily`，口径 {', '.join(versions) or '未知'}。",
        f"后续收益基准：指数 `{index_id}` 的收盘价（与状态同源、不额外选取有利区间）。",
        "UNKNOWN（数据不足）不计入后续收益统计，但计入覆盖与占比。",
        "样本为该状态出现的次数；同一段持续期内多次出现会重复计数——"
        "这是分布统计，不是独立事件研究。",
    ]
    if len(versions) != 1:
        notes.append("警告：状态历史里混了多个口径版本，跨版本比较没有意义。")

    # 与指数交易日对齐后再算后续收益：状态有、指数没有的日子不能前向填充。
    aligned = frame[frame["trade_date"].isin(price.index)]
    report = build_report(
        states=[str(value) for value in aligned["overall_state"].tolist()],
        index_close=price.loc[[day for day in aligned["trade_date"]]],
        unknown_state=LayerState.UNKNOWN.value,
        notes=notes,
    )

    by_year: dict[int, list[str]] = {}
    for trade_date, state in zip(aligned["trade_date"], aligned["overall_state"], strict=False):
        by_year.setdefault(int(str(trade_date)[:4]), []).append(str(state))

    context = [
        f"> 规则版本：`{PULSE_VERSION}` ｜ 生成时间："
        f"{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        ">",
        "> 本文由 `etf validate-pulse --write-doc` 生成，可随时重跑复现。",
        "",
        "## 0. 分年视图",
        "",
        "| 年份 | 交易日 | 切换次数 | UNKNOWN 占比 |",
        "| --- | --- | --- | --- |",
    ]
    for year in sorted(by_year):
        states = by_year[year]
        unknown = sum(1 for state in states if state == LayerState.UNKNOWN.value)
        switches = sum(1 for left, right in zip(states, states[1:], strict=False) if left != right)
        context.append(f"| {year} | {len(states)} | {switches} | {unknown / len(states):.1%} |")
    context.append("")

    markdown = render_markdown(
        report, title=f"pulse_v2 历史验证（{PULSE_VERSION}）", context=context
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
        "states": [
            {
                "state": item.state,
                "days": item.days,
                "share": item.share,
                "average_duration": item.average_duration,
            }
            for item in report.states
        ],
        "benchmark_index": index_id,
        "doc_path": str(target) if written else None,
        "markdown": markdown if not written else None,
    }
