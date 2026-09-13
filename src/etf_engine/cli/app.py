import json
from datetime import date
from pathlib import Path

import typer
import uvicorn

from etf_engine.audit import run_audit
from etf_engine.audit.runner import format_report
from etf_engine.config.settings import settings
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.research_context import ResearchContext
from etf_engine.jobs.backfill_flow import backfill_flow_history
from etf_engine.jobs.backfill_history import backfill_history
from etf_engine.jobs.backfill_index_history import backfill_index_history
from etf_engine.jobs.backfill_nav import backfill_nav
from etf_engine.jobs.compute_mart import compute_mart
from etf_engine.jobs.compute_pulse import backfill_pulse_history, compute_market_pulse
from etf_engine.jobs.sync_calendar import sync_calendar
from etf_engine.jobs.sync_fund_profile import sync_fund_profile
from etf_engine.jobs.sync_holdings import sync_holdings
from etf_engine.jobs.sync_index import sync_index_catalog, sync_index_details, sync_index_map
from etf_engine.jobs.sync_industry import sync_industry
from etf_engine.jobs.sync_market import sync_market
from etf_engine.jobs.sync_master import sync_master
from etf_engine.jobs.sync_nav import sync_nav
from etf_engine.jobs.sync_quotes import sync_quotes
from etf_engine.jobs.sync_shares import sync_shares
from etf_engine.mcp.server import run_stdio
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.services.core_metrics_service import ETFCoreMetricsService
from etf_engine.services.etf_service import ETFService
from etf_engine.services.research_service import ResearchService
from etf_engine.services.watchboard_service import WatchboardService

app = typer.Typer(help="A股 ETF 研究引擎")


def _research_context(
    asof: str | None,
    max_staleness_days: int | None,
    require_same_trade_date: bool,
) -> ResearchContext:
    """把 CLI 参数翻译成研究上下文（as-of 是 Point-in-Time 的入口）。"""
    try:
        return ResearchContext(
            asof_date=date.fromisoformat(asof) if asof else None,
            max_staleness_days=max_staleness_days,
            require_same_trade_date=require_same_trade_date,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("doctor")
def doctor():
    typer.echo("ETF Research Engine")
    typer.echo(f"env={settings.env}")
    typer.echo(f"database={settings.database_path}")
    typer.echo(f"raw={settings.raw_path}")
    typer.echo(f"timezone={settings.timezone}")

    db_parent = Path(settings.database_path).parent
    typer.echo(f"database_parent_exists={db_parent.exists()}")

    first_day, last_day, days = TradingCalendarRepository().bounds()
    typer.echo(f"trading_calendar_days={days}")
    typer.echo(f"trading_calendar_range={first_day}..{last_day}")
    if days == 0:
        typer.echo("提示：本地没有交易日历，请先执行 `etf sync-calendar`。")


@app.command("db-init")
def db_init():
    run_migrations()
    typer.echo(f"initialized: {settings.database_path}")


@app.command("sync-calendar")
def sync_calendar_cmd():
    result = sync_calendar()
    typer.echo(result)


@app.command("mcp")
def mcp():
    """以 stdio transport 启动 MCP server（需要 pip install -e ".[agent]"）。"""
    try:
        run_stdio()
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command("sync-master")
def sync_master_cmd():
    result = sync_master()
    typer.echo(result)


@app.command("sync-quotes")
def sync_quotes_cmd(trade_date: str | None = None):
    parsed = date.fromisoformat(trade_date) if trade_date else None
    result = sync_quotes(parsed)
    typer.echo(result)


@app.command("sync-shares")
def sync_shares_cmd(
    trade_date: str | None = None,
    backfill_days: int = typer.Option(
        1, "--backfill-days", "-b", help="回补最近N个交易日的份额（仅上交所支持）"
    ),
):
    parsed = date.fromisoformat(trade_date) if trade_date else None
    result = sync_shares(parsed, backfill_days=backfill_days)
    typer.echo(result)


@app.command("sync-nav")
def sync_nav_cmd(trade_date: str | None = None):
    parsed = date.fromisoformat(trade_date) if trade_date else None
    result = sync_nav(parsed)
    typer.echo(result)


@app.command("backfill-nav")
def backfill_nav_cmd(
    security_ids: list[str] = typer.Option(
        None, "--security-id", "-s", help="指定待回补净值的证券代码"
    ),
    days: int = typer.Option(60, "--days", "-d", help="需要覆盖的交易日数量"),
    limit: int = typer.Option(50, "--limit", "-n", help="本次最多回补多少只基金"),
    sleep_seconds: float = typer.Option(0.3, "--sleep", help="每只基金之间的间隔秒数"),
):
    result = backfill_nav(
        security_ids=security_ids or None,
        days=days,
        limit=limit,
        sleep_seconds=sleep_seconds,
    )
    typer.echo(result)


@app.command("backfill-history")
def backfill_history_cmd(
    security_ids: list[str] = typer.Option(
        None, "--security-id", "-s", help="指定待回补历史的证券代码"
    ),
    days: int = typer.Option(90, "--days", "-d", help="回补历史天数"),
    top_n: int = typer.Option(20, "--top-n", "-n", help="按成交额自动选取前N只ETF"),
):
    result = backfill_history(security_ids=security_ids or None, days=days, top_n=top_n)
    typer.echo(result)


@app.command("compute-mart")
def compute_mart_cmd(
    security_ids: list[str] = typer.Option(None, "--security-id", "-s", help="指定计算指标的ETF"),
):
    result = compute_mart(security_ids=security_ids or None)
    typer.echo(result)


@app.command("compare")
def compare_cmd(
    security_ids: list[str] = typer.Argument(
        ..., help="待对比的ETF代码列表，例如 588200.SH 159915.SZ"
    ),
    asof: str = typer.Option(None, "--asof", help="研究截止日（Point-in-Time），如 2026-09-11"),
    max_staleness_days: int = typer.Option(
        None, "--max-staleness-days", help="允许的数据滞后天数，超过则该项置空"
    ),
    require_same_day: bool = typer.Option(
        False, "--require-same-day", help="只使用与 as-of 同一天的数据"
    ),
):
    context = _research_context(asof, max_staleness_days, require_same_day)
    results = ResearchService().compare(security_ids, context)
    if not results:
        typer.echo("未找到待对比的 ETF 数据。")
        return
    for item in results:
        typer.echo(
            f"[{item['security_id']}] {item['fund_name']} | "
            f"最新价: {item['close']} ({item['change_pct']}%) | "
            f"20D收益: {item['return_20d']} | "
            f"60D回撤: {item['max_drawdown_60d']} | "
            f"估算规模: {item['estimated_aum']} | "
            f"20D均成交: {item['avg_turnover_amount_20d']}"
        )
        typer.echo(
            f"    as-of: research={item['research_asof_date']} "
            f"quote={item['quote_asof_date']} share={item['share_asof_date']} "
            f"metric={item['metric_asof_date']} flow={item['flow_asof_date']} "
            f"| 质量={item['data_quality']}"
            + (f" | 置空: {'; '.join(item['stale_blocks'])}" if item["stale_blocks"] else "")
        )


@app.command("sync-holdings")
def sync_holdings_cmd(
    security_ids: list[str] = typer.Option(
        None, "--security-id", "-s", help="指定待抓取持仓的证券代码"
    ),
    top_n: int = typer.Option(20, "--top-n", "-n", help="按成交额自动选取前N只ETF"),
):
    result = sync_holdings(security_ids=security_ids or None, top_n=top_n)
    typer.echo(result)


@app.command("sync-industry")
def sync_industry_cmd(
    security_ids: list[str] = typer.Option(
        None, "--security-id", "-s", help="指定待同步行业分类的个股"
    ),
    sleep_seconds: float = typer.Option(0.2, "--sleep", help="每只个股之间的间隔秒数"),
):
    result = sync_industry(security_ids=security_ids or None, sleep_seconds=sleep_seconds)
    typer.echo(result)


@app.command("sync-index-catalog")
def sync_index_catalog_cmd():
    typer.echo(sync_index_catalog())


@app.command("sync-fund-profile")
def sync_fund_profile_cmd(
    security_ids: list[str] = typer.Option(
        None, "--security-id", "-s", help="指定待补齐档案的 ETF"
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="本次最多处理多少只 ETF"),
    sleep_seconds: float = typer.Option(0.3, "--sleep", help="每只 ETF 之间的间隔秒数"),
):
    """补齐 master 的费率/成立日期/管理人/托管人等档案字段。"""
    typer.echo(
        sync_fund_profile(
            security_ids=security_ids or None, limit=limit, sleep_seconds=sleep_seconds
        )
    )


@app.command("sync-index-map")
def sync_index_map_cmd(
    security_ids: list[str] = typer.Option(
        None, "--security-id", "-s", help="指定待映射跟踪指数的 ETF"
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="本次最多处理多少只 ETF"),
    sleep_seconds: float = typer.Option(0.3, "--sleep", help="每只 ETF 之间的间隔秒数"),
):
    typer.echo(
        sync_index_map(security_ids=security_ids or None, limit=limit, sleep_seconds=sleep_seconds)
    )


@app.command("sync-index-details")
def sync_index_details_cmd(
    limit_indices: int = typer.Option(None, "--limit", "-n", help="最多处理多少个指数"),
    quote_trading_days: int = typer.Option(90, "--days", "-d", help="指数行情回溯交易日数"),
):
    typer.echo(
        sync_index_details(limit_indices=limit_indices, quote_trading_days=quote_trading_days)
    )


@app.command("screen")
def screen_cmd(
    query: str = typer.Option(None, "--query", "-q", help="按代码或名称模糊搜索"),
    tag: str = typer.Option(
        None, "--tag", "-t", help="按穿透行业/风格标签筛选（如通信设备、半导体）"
    ),
    min_aum: float = typer.Option(None, "--min-aum", help="最小规模（元）"),
    min_turnover_20d: float = typer.Option(None, "--min-turnover", help="20日最小日均成交额（元）"),
    min_return_20d: float = typer.Option(
        None, "--min-return-20d", help="20日最小收益率（如 0.05 代表5%）"
    ),
    max_drawdown_60d: float = typer.Option(
        None, "--max-drawdown-60d", help="60日最大回撤阈值（如 -0.15）"
    ),
    share_growth: bool = typer.Option(False, "--share-growth", help="仅筛选20日份额增加的ETF"),
    limit: int = typer.Option(20, "--limit", "-l", help="返回数量限制"),
    asof: str = typer.Option(None, "--asof", help="研究截止日（Point-in-Time），如 2026-09-11"),
    max_staleness_days: int = typer.Option(
        None, "--max-staleness-days", help="允许的数据滞后天数，超过则该数据块置空"
    ),
):
    results = ResearchService().screen(
        context=_research_context(asof, max_staleness_days, False),
        query=query,
        tag=tag,
        min_aum=min_aum,
        min_turnover_20d=min_turnover_20d,
        min_return_20d=min_return_20d,
        max_drawdown_60d=max_drawdown_60d,
        share_growth_only=share_growth,
        limit=limit,
    )
    if not results:
        typer.echo("没有满足筛选条件的 ETF。")
        return
    typer.echo(f"筛选到 {len(results)} 只符合条件的 ETF：")
    for r in results:
        ret_val = r.get("return_20d")
        ret_str = f"{ret_val * 100:.2f}%" if ret_val is not None else "—"
        aum_val = r.get("aum")
        aum_str = f"{aum_val:>12,.0f}" if aum_val is not None else f"{'—':>12}"
        tags_str = f"[{r['tags']}]" if r.get("tags") else ""
        typer.echo(
            f"{r['security_id']:<10} {r['fund_name']:<18} "
            f"规模: {aum_str} | "
            f"20D均量: {r['avg_turnover_amount_20d'] or 0:>12,.0f} | "
            f"20D收益: {ret_str:>7} {tags_str}"
        )


@app.command("themes")
def themes_cmd(
    limit: int = typer.Option(20, "--limit", "-l", help="返回数量限制"),
    min_etf_count: int = typer.Option(1, "--min-etf", help="主题下最少 ETF 数量"),
):
    """按标签聚合主题（行业 / 风格）。"""
    results = ResearchService().themes(limit=limit, min_etf_count=min_etf_count)
    if not results:
        typer.echo("本地还没有主题标签。先执行 `etf sync-holdings` 与 `etf sync-industry`。")
        return
    for item in results:
        aum = item.get("total_estimated_aum")
        aum_str = f"{aum / 1e8:,.1f}亿" if aum is not None else "—"
        typer.echo(
            f"{item['theme']:<14} [{item['tag_type']:<8}] "
            f"ETF数: {item['etf_count']:>3} | 合计规模: {aum_str:>12} | "
            f"20D均收益: {item.get('avg_return_20d') or 0:>7.2%}"
        )


@app.command("show")
def show(security_id: str):
    result = ETFService().get_latest_snapshot(security_id)
    typer.echo(result)


@app.command("metrics")
def metrics(security_id: str, asof_date: str | None = None):
    parsed_date = date.fromisoformat(asof_date) if asof_date else None
    try:
        result = ETFCoreMetricsService().get_core_metrics(security_id, parsed_date)
    except (LookupError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(result.model_dump_json(indent=2))


@app.command("api")
def api(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
):
    uvicorn.run("etf_engine.api.app:app", host=host, port=port, reload=False)


@app.command("sync-market")
def sync_market_cmd(
    backfill_days: int = typer.Option(
        120, "--backfill-days", "-d", help="成交额回补的交易日数量（250 可解锁完整分位窗口）"
    ),
    margin_days: int = typer.Option(300, "--margin-days", help="两融余额覆盖的交易日数量"),
):
    """同步看盘台市场层：成交额 / 两融 / 估值 / 涨跌家数。"""
    result = sync_market(backfill_days=backfill_days, margin_days=margin_days)
    typer.echo(result)


@app.command("backfill-index-history")
def backfill_index_history_cmd(
    index_ids: list[str] = typer.Option(
        None, "--index-id", "-i", help="指定待回补的指数代码（默认宽基篮子 + 上证指数）"
    ),
    years: int = typer.Option(6, "--years", "-y", help="回补年数"),
    sleep_seconds: float = typer.Option(0.3, "--sleep", help="每只指数之间的间隔秒数"),
):
    """回补宽基指数长历史（位置分位用）。"""
    result = backfill_index_history(
        index_ids=index_ids or None, years=years, sleep_seconds=sleep_seconds
    )
    typer.echo(result)


@app.command("pulse")
def pulse_cmd(
    asof_date: str | None = typer.Option(None, "--asof-date", help="指定 as-of 日期"),
    json_output: bool = typer.Option(False, "--json", help="输出完整 JSON"),
):
    """计算并打印三层看盘状态（同时写入 mart.market_pulse_daily）。"""
    parsed = date.fromisoformat(asof_date) if asof_date else None
    result = compute_market_pulse(asof=parsed)
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return
    payload = WatchboardService().watchboard(asof_date=parsed)
    meta = payload.get("meta", {})
    typer.echo(f"看盘台 as-of {meta.get('asof_date')} · 规则版本 {meta.get('calculation_version')}")
    typer.echo(
        f"共振结论：{meta.get('overall_state')} "
        f"（{meta.get('strong_layers')}/{meta.get('known_layers')} 层偏强）"
    )
    if meta.get("quadrant_label"):
        typer.echo(f"量价象限：{meta['quadrant_label']}")
    typer.echo("-" * 62)
    for layer in payload.get("layers", []):
        typer.echo(f"{layer['label']} [{layer['state']}] {layer['question']}")
        typer.echo(f"    {layer['note']}")
        typer.echo(f"    覆盖：{layer['coverage']}｜未接入：{layer['unavailable']}")
    typer.echo("-" * 62)
    for line in payload.get("gaps", []):
        typer.echo(f"缺口：{line}")


@app.command("backfill-flow")
def backfill_flow_cmd(
    security_ids: list[str] = typer.Option(
        None, "--security-id", "-s", help="只回填指定 ETF（默认全部有份额历史的 ETF）"
    ),
):
    """按份额历史逐日回填申赎估算（mart.etf_flow_daily）。"""
    result = backfill_flow_history(security_ids=security_ids or None)
    typer.echo(result)


@app.command("backfill-pulse")
def backfill_pulse_cmd(
    days: int = typer.Option(250, "--days", "-d", help="回放的交易日数量"),
    asof_date: str | None = typer.Option(None, "--asof-date", help="回放的截止交易日"),
):
    """逐日回放三层状态，写入 mart.market_pulse_daily（状态历史热力图用）。"""
    parsed = date.fromisoformat(asof_date) if asof_date else None
    result = backfill_pulse_history(days=days, asof=parsed)
    typer.echo(result)


@app.command("audit")
def audit_cmd(
    json_output: bool = typer.Option(False, "--json", help="输出 JSON（给 Agent / CI 消费）"),
    strict: bool = typer.Option(False, "--strict", help="WARN 也视为失败"),
    samples: int = typer.Option(5, "--samples", help="每条规则最多展示多少条明细"),
):
    """自检：架构约束 + 数据不变量（AGENTS.md 的可执行版本）。

    有 ERROR 级违规时以非 0 退出，因此可以直接挂在每日链路或 CI 后面。
    """
    result = run_audit()
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        typer.echo(format_report(result, show_samples=samples))

    failed = result["error_count"] > 0 or (strict and result["warning_count"] > 0)
    if failed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
