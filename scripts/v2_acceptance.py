"""V2 总体验收（升级方案 §12）：用当时可获得的数据做一次完整研究。

选题：用行业标签表达国产算力产业链（集成电路 / 半导体材料与设备 / 通信设备），
在 as-of 当天挑出候选，再逐只回答：跟踪指数、主要成分与行业暴露、持仓重合度、
规模、流动性、费率、20/60 日跟踪差异与误差、份额变化与估算净申购、当前回撤、
同类分位、数据新鲜度与缺口。

所有查询都走 Application Service（与 CLI/API/MCP 同一条路径），带 as-of；
缺失维度如实说明"缺什么、为什么"，不做任何近似。

用法::

    python scripts/v2_acceptance.py --asof 2026-09-11 --write-doc
"""

import argparse
from datetime import date
from pathlib import Path

from etf_engine.domain.research_context import ResearchContext
from etf_engine.repositories.holding_repository import HoldingRepository
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.peer_repository import PeerRepository
from etf_engine.services.core_metrics_service import ETFCoreMetricsService
from etf_engine.services.peer_service import PeerService
from etf_engine.services.research_service import ResearchService

# 国产算力在本系统的可核对表达：中证行业分类标签，而不是关键词猜名字。
COMPUTE_TAGS = ("集成电路", "半导体材料与设备", "通信设备")
DEFAULT_DOC = Path("docs/V2_ACCEPTANCE.md")


def _fmt(value, *, pct=False, money=False, digits=2) -> str:
    if value is None:
        return "—"
    if pct:
        return f"{value * 100:+.{digits}f}%"
    if money:
        return f"{value / 1e8:,.1f}亿"
    return f"{value:,.{digits}f}"


def collect(asof: date, limit: int) -> dict:
    context = ResearchContext(asof_date=asof)
    research = ResearchService()
    peers = PeerService()
    metrics_service = ETFCoreMetricsService()
    master_repository = MasterRepository()
    holding_repository = HoldingRepository()
    peer_repository = PeerRepository()

    candidates: dict[str, dict] = {}
    for tag in COMPUTE_TAGS:
        for row in research.screen(tag=tag, context=context, limit=limit * 3):
            candidates[row["security_id"]] = row

    ordered = sorted(candidates.values(), key=lambda row: -(row.get("aum") or 0))[:limit]
    security_ids = [row["security_id"] for row in ordered]

    peer_rows = {
        row["security_id"]: row for row in peers.compare_peers(security_ids, asof_date=asof)
    }
    overlap = peers.exposure_overlap(security_ids)

    rows: list[dict] = []
    for screen_row in ordered:
        security_id = screen_row["security_id"]
        master = master_repository.get_by_id(security_id) or {}
        holdings, report_date = holding_repository.get_latest_top10(security_id)
        peer_row = peer_rows.get(security_id, {})
        group = peer_repository.group_of(security_id) or {}
        try:
            metrics = metrics_service.get_core_metrics(security_id, asof)
        except (LookupError, ValueError) as exc:
            rows.append({"security_id": security_id, "error": str(exc)})
            continue

        source_dates = metrics.quality.source_asof_dates
        rows.append(
            {
                "security_id": security_id,
                "name": screen_row.get("fund_name"),
                "tracking_index": (
                    f"{master.get('tracking_index_id')} {master.get('tracking_index_name')}"
                    if master.get("tracking_index_id")
                    else (master.get("tracking_index_name") or "—")
                ),
                "aum": screen_row.get("aum"),
                "turnover_20d": screen_row.get("avg_turnover_amount_20d"),
                "fee": master.get("management_fee_pct"),
                "custodian_fee": master.get("custodian_fee_pct"),
                "return_20d": screen_row.get("return_20d"),
                "return_60d": screen_row.get("return_60d"),
                "drawdown": metrics.max_drawdown_60d,
                "tracking_error": metrics.tracking_error_60d,
                "share_change_20d": metrics.share_change_20d,
                "subscription_20d": metrics.estimated_net_subscription_20d,
                "tags": screen_row.get("tags"),
                "peer_group": group.get("peer_group_id"),
                "peer_count": group.get("peer_count"),
                "peer_ranks": {
                    key: list(metrics_map.values())[0]
                    for key, metrics_map in (peer_row.get("dimensions") or {}).items()
                },
                "holdings": [
                    {
                        "stock_id": item["stock_id"],
                        "name": item["stock_name"],
                        "weight": item["weight_pct"],
                    }
                    for item in holdings[:5]
                ],
                "holdings_report_date": report_date.isoformat() if report_date else None,
                "asof": {
                    "research": metrics.asof_date.isoformat(),
                    "quote": source_dates["quote"].isoformat()
                    if source_dates.get("quote")
                    else None,
                    "share": source_dates["share"].isoformat()
                    if source_dates.get("share")
                    else None,
                    "holdings": metrics.holdings_asof_date.isoformat()
                    if metrics.holdings_asof_date
                    else None,
                },
                "gaps": dict(metrics.quality.reasons),
            }
        )
    return {"asof": asof.isoformat(), "rows": rows, "overlap": overlap}


def render(payload: dict) -> str:
    rows = payload["rows"]
    lines = [
        "# V2 总体验收：国产算力 ETF 研究（Point-in-Time）",
        "",
        "> 升级方案 §12 的验收 case。所有维度都走 Application Service"
        "（与 CLI/API/MCP 同一路径），统一 as-of **" + payload["asof"] + "**，"
        "只使用当天（含）之前的数据。",
        "",
        "选题口径：用中证行业分类标签表达国产算力产业链"
        "（集成电路 / 半导体材料与设备 / 通信设备），不按 ETF 名称模糊匹配。",
        "",
        "> 注意：标签是**前十大持仓穿透**出来的行业暴露，不等于基金的主题定位——"
        "宽基 ETF 也可能因为重仓股集中在某行业而带上标签（例如沪深300 带通信设备）。"
        "判断主题是否纯粹，请看第 2 节的成分与第 3 节的行业重合度。",
        "",
        "## 1. 候选与横向对比",
        "",
        "| 代码 | 名称 | 跟踪指数 | 规模 | 20日均成交 | 管理费 | 20日收益 | 当前回撤"
        " | 跟踪误差 | 20日份额变化 | 20日估算净申购 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        if row.get("error"):
            lines.append(f"| {row['security_id']} | 无本地行情：{row['error']} | | | | | | | | | |")
            continue
        lines.append(
            f"| {row['security_id']} | {row['name']} | {row['tracking_index']} "
            f"| {_fmt(row['aum'], money=True)} | {_fmt(row['turnover_20d'], money=True)} "
            f"| {_fmt(row['fee'])} | {_fmt(row['return_20d'], pct=True)} "
            f"| {_fmt(row['drawdown'], pct=True)} | {_fmt(row['tracking_error'], pct=True)} "
            f"| {_fmt(row['share_change_20d'], money=True)} "
            f"| {_fmt(row['subscription_20d'], money=True)} |"
        )

    lines += ["", "## 2. 主要成分与行业暴露", ""]
    for row in rows:
        if row.get("error"):
            continue
        lines.append(f"**{row['security_id']} {row['name']}**（标签：{row['tags'] or '—'}）")
        if row["holdings"]:
            top = "、".join(f"{item['name']}({item['weight']}%)" for item in row["holdings"])
            lines.append(f"- 前五大：{top}（报告期 {row['holdings_report_date']}）")
        else:
            lines.append("- 前五大：—（本地没有该 ETF 的披露持仓）")
        lines.append("")

    lines += ["## 3. ETF 间持仓重合度", ""]
    pairs = payload["overlap"]["pairs"]
    if not pairs:
        lines.append("（候选里没有两只有持仓的 ETF 可比较）")
    else:
        lines += [
            "| A | B | 共同持仓 | 重合度 | 加权重合 | Top10 重合 | 行业重合 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for pair in pairs[:15]:
            lines.append(
                f"| {pair['left']} | {pair['right']} | {len(pair['common_holdings'])} "
                f"| {_fmt(pair['holding_overlap_ratio'])} | {_fmt(pair['weighted_overlap'])} "
                f"| {_fmt(pair['top10_overlap'])} | {_fmt(pair['industry_overlap'])} |"
            )
        lines += ["", f"持仓覆盖（每只 ETF 的持仓条数）：{payload['overlap']['coverage']}"]

    lines += ["", "## 4. 同类分位（1.0 = 同类最优）", ""]
    for row in rows:
        if row.get("error"):
            continue
        ranks = row.get("peer_ranks") or {}
        rendered = [
            f"{dimension}={'—' if value is None else f'{value * 100:.0f}%'}"
            for dimension, value in ranks.items()
        ]
        lines.append(
            f"- **{row['security_id']}** 同类组 {row['peer_group']}（n={row['peer_count']}）："
            + (" ".join(rendered) if rendered else "—")
        )

    lines += ["", "## 5. 数据新鲜度与缺口", ""]
    for row in rows:
        if row.get("error"):
            continue
        asof = row["asof"]
        lines.append(
            f"- **{row['security_id']}** 研究 as-of={asof['research']}"
            f"（行情 {asof['quote']} · 份额 {asof['share']} · 持仓 {asof['holdings']}）"
        )
        if row["gaps"]:
            summary = "、".join(f"{key}={reason}" for key, reason in list(row["gaps"].items())[:6])
            lines.append(f"  - 缺口：{summary}")

    lines += [
        "",
        "## 6. 结论边界",
        "",
        "- 只输出事实与派生指标，不含任何买卖建议；",
        "- 每个维度都可追到 core.* 的原始来源与 as-of 日期；",
        "- 缺失维度显示为 — 并给出原因（insufficient_history /"
        " benchmark_return_basis_unknown 等），不用 0 或近似值顶替；",
        "- 口径版本：复权 adjust_v1、同类分位 peer_v1、市场标准化 market_norm_v1。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 总体验收")
    parser.add_argument("--asof", default="2026-09-11")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--write-doc", action="store_true")
    parser.add_argument("--doc", default=str(DEFAULT_DOC))
    args = parser.parse_args()

    payload = collect(date.fromisoformat(args.asof), args.limit)
    markdown = render(payload)
    if args.write_doc:
        target = Path(args.doc)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        print(f"报告已写入 {target}")
    else:
        print(markdown)


if __name__ == "__main__":
    main()
