"""多源交叉对账工具：AkShare vs WeStock 数据一致性核验。

对关键 ETF（如 510300.SH, 159915.SZ, 512890.SH）同时发起 AkShare 和 WeStock 采集，
在标准化 Domain Model 层比对价格、成交额、净值、持仓重合度，检验数据源一致性与分歧。
"""

import argparse
from datetime import date
from decimal import Decimal

from etf_engine.domain.identifiers import SecurityId
from etf_engine.sources.akshare.holdings import AkshareETFHoldingSource
from etf_engine.sources.akshare.nav import AkshareETFNavSource
from etf_engine.sources.akshare.quotes import AkshareETFQuoteSource
from etf_engine.sources.westock.holdings import WestockETFHoldingSource
from etf_engine.sources.westock.nav import WestockETFNavSource
from etf_engine.sources.westock.quotes import WestockETFQuoteSource


def cross_check(security_id: str):
    sid = SecurityId.parse(security_id).value
    print(f"\n{'='*30} 交叉核验: {sid} {'='*30}")

    # 1. 行情比对
    print("\n[1. 行情与估值比对]")
    ak_quotes = {q.security_id: q for q in AkshareETFQuoteSource().fetch_quotes()}
    ws_quotes = {q.security_id: q for q in WestockETFQuoteSource().fetch_quotes(security_ids=[sid])}

    ak_q = ak_quotes.get(sid)
    ws_q = ws_quotes.get(sid)

    print(f"{'指标':<18} | {'AkShare (东财)':<20} | {'WeStock (腾讯)':<20} | {'差异/结论'}")
    print("-" * 75)
    if ak_q and ws_q:
        items = [
            ("最新价 (close)", ak_q.close, ws_q.close),
            ("涨跌幅 (change_pct)", ak_q.change_pct, ws_q.change_pct),
            ("成交额 (turnover)", f"{ak_q.turnover_amount:,.0f}" if ak_q.turnover_amount else "NULL",
                                f"{ws_q.turnover_amount:,.0f}" if ws_q.turnover_amount else "NULL"),
            ("IOPV / 净值", ak_q.iopv, ws_q.iopv),
            ("折溢价率 (%)", ak_q.premium_discount_pct, ws_q.premium_discount_pct),
        ]
        for name, v1, v2 in items:
            diff = "一致" if str(v1) == str(v2) else f"Δ: {v1} vs {v2}"
            print(f"{name:<18} | {str(v1):<20} | {str(v2):<20} | {diff}")
    else:
        print("未能同时获取到两方行情快照。")

    # 2. 持仓比对
    print("\n[2. 持仓明细比对 (Top 5)]")
    try:
        ak_holdings = AkshareETFHoldingSource().fetch_holdings(sid)[:5]
    except Exception as exc:
        ak_holdings = []
        print(f"AkShare 持仓拉取失败: {exc}")

    try:
        ws_holdings = WestockETFHoldingSource().fetch_holdings(sid)[:5]
    except Exception as exc:
        ws_holdings = []
        print(f"WeStock 持仓拉取失败: {exc}")

    print("AkShare (季度披露季报口径):")
    for h in ak_holdings:
        print(f"  - {h.stock_id:<9} {h.stock_name:<8} 权重: {h.weight_pct:.2f}% (报告期: {h.report_date})")

    print("WeStock (PCF 申赎清单最新口径):")
    for h in ws_holdings:
        print(f"  - {h.stock_id:<9} {h.stock_name:<8} 权重: {h.weight_pct:.2f}% (清单日: {h.disclosure_date})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETF 多源交叉对账")
    parser.add_argument("security_id", nargs="?", default="510300.SH", help="目标 ETF 代码")
    args = parser.parse_args()
    cross_check(args.security_id)
