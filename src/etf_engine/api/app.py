from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from etf_engine.jobs.compute_mart import compute_mart
from etf_engine.jobs.sync_holdings import sync_holdings
from etf_engine.jobs.sync_master import sync_master
from etf_engine.jobs.sync_quotes import sync_quotes
from etf_engine.jobs.sync_shares import sync_shares

from etf_engine.services.core_metrics_service import ETFCoreMetricsService
from etf_engine.services.etf_service import ETFService
from etf_engine.services.research_service import ResearchService

app = FastAPI(
    title="ETF Research Engine",
    version="0.1.0",
)

service = ETFService()
core_metrics_service = ETFCoreMetricsService()
research_service = ResearchService()
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
def sync_latest_shares(trade_date: date | None = None):
    try:
        result = sync_shares(trade_date=trade_date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"份额同步失败：{exc}") from exc
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


