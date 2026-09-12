from datetime import date
from pathlib import Path

import typer
import uvicorn

from etf_engine.config.settings import settings
from etf_engine.db.migrate import run_migrations
from etf_engine.jobs.backfill_history import backfill_history
from etf_engine.jobs.backfill_nav import backfill_nav
from etf_engine.jobs.compute_mart import compute_mart
from etf_engine.jobs.sync_calendar import sync_calendar
from etf_engine.jobs.sync_holdings import sync_holdings
from etf_engine.jobs.sync_master import sync_master
from etf_engine.jobs.sync_nav import sync_nav
from etf_engine.jobs.sync_quotes import sync_quotes
from etf_engine.jobs.sync_shares import sync_shares
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.services.core_metrics_service import ETFCoreMetricsService
from etf_engine.services.etf_service import ETFService
from etf_engine.services.research_service import ResearchService

app = typer.Typer(help="A股 ETF 研究引擎")


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
):
    results = ResearchService().compare(security_ids)
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


@app.command("sync-holdings")
def sync_holdings_cmd(
    security_ids: list[str] = typer.Option(
        None, "--security-id", "-s", help="指定待抓取持仓的证券代码"
    ),
    top_n: int = typer.Option(20, "--top-n", "-n", help="按成交额自动选取前N只ETF"),
):
    result = sync_holdings(security_ids=security_ids or None, top_n=top_n)
    typer.echo(result)


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
):
    results = ResearchService().screen(
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


if __name__ == "__main__":
    app()
