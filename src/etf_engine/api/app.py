from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from etf_engine.jobs.backfill_index_history import backfill_index_history
from etf_engine.jobs.backfill_nav import backfill_nav
from etf_engine.jobs.compute_mart import compute_mart
from etf_engine.jobs.compute_pulse import compute_market_pulse
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
from etf_engine.services.core_metrics_service import ETFCoreMetricsService
from etf_engine.services.etf_service import ETFService
from etf_engine.services.research_service import ResearchService
from etf_engine.services.watchboard_service import WatchboardService

app = FastAPI(
    title="ETF Research Engine",
    version="0.1.0",
)

service = ETFService()
core_metrics_service = ETFCoreMetricsService()
research_service = ResearchService()
watchboard_service = WatchboardService()
WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def dashboard_page():
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/api/v1/dashboard")
def dashboard():
    data = service.dashboard_summary()
    latest_trade_date = data["latest_trade_date"]
    return {
        "data": data,
        "meta": {
            "asof_date": latest_trade_date.isoformat() if latest_trade_date else None,
            "quality": "PASS" if latest_trade_date else "EMPTY",
        },
        "errors": [],
    }


@app.get("/api/v1/etfs")
def search_etfs(
    query: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
):
    return {"data": service.search_etfs(query=query, limit=limit), "meta": {}, "errors": []}


@app.post("/api/v1/sync/quotes")
def sync_latest_quotes():
    try:
        result = sync_quotes()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"行情同步失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/sync/master")
def sync_latest_master():
    try:
        result = sync_master()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ETF 基础资料同步失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/sync/shares")
def sync_latest_shares(trade_date: date | None = None, backfill_days: int = 1):
    try:
        result = sync_shares(trade_date=trade_date, backfill_days=backfill_days)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"份额同步失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/sync/calendar")
def sync_trading_calendar():
    try:
        result = sync_calendar()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"交易日历同步失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/sync/nav")
def sync_latest_nav(trade_date: date | None = None):
    try:
        result = sync_nav(trade_date=trade_date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"净值同步失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.get("/api/v1/etfs/{security_id}")
def get_etf(security_id: str):
    try:
        data = service.get_latest_snapshot(security_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = {
        "data": data,
        "meta": {},
        "errors": [],
    }
    if data["quote"] is None:
        raise HTTPException(
            status_code=404, detail=f"本地尚未找到 {data['security_id']} 的行情数据"
        )
    return response


@app.get("/api/v1/etfs/{security_id}/core-metrics")
def get_core_metrics(security_id: str, asof_date: date | None = None):
    try:
        metrics = core_metrics_service.get_core_metrics(security_id, asof_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "data": metrics.model_dump(mode="json"),
        "meta": {
            "asof_date": metrics.asof_date.isoformat(),
            "quality": metrics.quality.status,
        },
        "errors": [],
    }


@app.post("/api/v1/compute/mart")
def trigger_compute_mart(security_ids: list[str] | None = None):
    try:
        result = compute_mart(security_ids=security_ids)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Mart 计算失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.get("/api/v1/research/compare")
def compare_etfs(security_ids: str = Query(..., description="逗号分隔的ETF代码列表")):
    ids = [sid.strip() for sid in security_ids.split(",") if sid.strip()]
    data = research_service.compare(ids)
    return {"data": data, "meta": {"count": len(data)}, "errors": []}


@app.post("/api/v1/sync/holdings")
def sync_latest_holdings(security_ids: list[str] | None = None, top_n: int = 20):
    try:
        result = sync_holdings(security_ids=security_ids, top_n=top_n)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"持仓与行业标签同步失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/sync/industry")
def sync_stock_industry(security_ids: list[str] | None = None):
    """个股行业分类（逐只标的，默认只同步已被持仓覆盖的个股）。"""
    try:
        result = sync_industry(security_ids=security_ids)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"行业分类同步失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/sync/fund-profile")
def sync_fund_profiles(security_ids: list[str] | None = None, limit: int = 50):
    """补齐 master 的费率/成立日期/管理人/托管人等档案字段。"""
    try:
        result = sync_fund_profile(security_ids=security_ids, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"基金档案同步失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/sync/index/catalog")
def sync_indices_catalog():
    try:
        result = sync_index_catalog()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"指数目录同步失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/sync/index/map")
def sync_etf_index_map(limit: int = 50):
    try:
        result = sync_index_map(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"跟踪指数映射失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/sync/index/details")
def sync_indices_details(limit_indices: int | None = None, quote_trading_days: int = 90):
    try:
        result = sync_index_details(
            limit_indices=limit_indices, quote_trading_days=quote_trading_days
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"指数成分/行情同步失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/backfill/nav")
def trigger_backfill_nav(
    security_ids: list[str] | None = None,
    days: int = 60,
    limit: int | None = 50,
):
    """逐只基金回补净值历史（有界、限速、可续跑）。"""
    try:
        result = backfill_nav(security_ids=security_ids, days=days, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"净值历史回补失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.get("/api/v1/research/screen")
def screen_etfs(
    query: str | None = None,
    tag: str | None = None,
    min_aum: float | None = None,
    min_turnover_20d: float | None = None,
    min_return_20d: float | None = None,
    max_drawdown_60d: float | None = None,
    share_growth_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
):
    data = research_service.screen(
        query=query,
        tag=tag,
        min_aum=min_aum,
        min_turnover_20d=min_turnover_20d,
        min_return_20d=min_return_20d,
        max_drawdown_60d=max_drawdown_60d,
        share_growth_only=share_growth_only,
        limit=limit,
    )
    return {"data": data, "meta": {"count": len(data)}, "errors": []}


@app.get("/api/v1/research/themes")
def list_themes(
    limit: int = Query(default=50, ge=1, le=200),
    min_etf_count: int = Query(default=1, ge=1),
):
    data = research_service.themes(limit=limit, min_etf_count=min_etf_count)
    return {"data": data, "meta": {"count": len(data)}, "errors": []}


@app.get("/watchboard")
def watchboard_page():
    """看盘台页面（布局见 docs/WATCHBOARD.md 第 3 节）。"""
    return FileResponse(WEB_ROOT / "watchboard.html")


@app.get("/api/v1/watchboard")
def watchboard(asof_date: date | None = None, basket_limit: int = Query(default=50, ge=1, le=200)):
    data = watchboard_service.watchboard(asof_date=asof_date, basket_limit=basket_limit)
    meta = data.get("meta", {})
    return {
        "data": data,
        "meta": {
            "asof_date": meta.get("asof_date"),
            "quality": meta.get("quality", "PASS"),
            "calculation_version": meta.get("calculation_version"),
        },
        "errors": [],
    }


@app.get("/api/v1/watchboard/history")
def watchboard_history(limit: int = Query(default=120, ge=1, le=500)):
    data = watchboard_service.history(limit=limit)
    return {"data": data, "meta": {"count": len(data)}, "errors": []}


@app.post("/api/v1/sync/market")
def sync_market_data(
    backfill_days: int = Query(default=120, ge=1, le=500),
    margin_days: int = Query(default=300, ge=30, le=2000),
):
    try:
        result = sync_market(backfill_days=backfill_days, margin_days=margin_days)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"市场层同步失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/backfill/index-history")
def backfill_index_history_api(years: int = Query(default=6, ge=1, le=20)):
    try:
        result = backfill_index_history(years=years)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"指数历史回补失败：{exc}") from exc
    return {"data": result, "meta": {}, "errors": []}


@app.post("/api/v1/compute/pulse")
def compute_pulse_api(asof_date: date | None = None):
    try:
        result = compute_market_pulse(asof=asof_date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"三层状态计算失败：{exc}") from exc
    return {"data": result, "meta": {"asof_date": str(result.get("trade_date"))}, "errors": []}
