"""看盘台前端的渲染回归测试（用 Node 跑真实 JS，不引入浏览器依赖）。

为什么需要它：这一层是"数字 → 文字"的最后一道，单位/符号错了界面照样好看。
实测已经踩过两次：

* `const cls = ... cls(...)` 自引用，页面整体白屏（TDZ 报错）；
* 折溢价（比例，0.0015）与涨跌幅（百分数，-1.69）共用同一个格式化函数，
  结果涨跌幅显示成 -169.00%。

测试在缺少 Node 时跳过，不让前端校验拖垮后端 CI。
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB_ROOT = Path(__file__).resolve().parents[2] / "src" / "etf_engine" / "web"
RUNNER = """
const fs = require("node:fs");
// `node -e script a b` 的 argv 与脚本文件模式不同，取最后两个参数最稳。
const [htmlPath, payloadPath] = process.argv.slice(-2);
const html = fs.readFileSync(htmlPath, "utf8");
const payload = JSON.parse(fs.readFileSync(payloadPath, "utf8"));
const js = html.match(/<script>([\\s\\S]*?)<\\/script>/)[1];
const makeElement = () => ({
  innerHTML: "",
  textContent: "",
  dataset: {},
  classList: { add() {}, remove() {}, toggle() {} },
  addEventListener() {},
  setAttribute() {},
  getAttribute() { return null; },
  querySelectorAll() { return []; },
  querySelector() { return null; },
  closest() { return null; },
});
const store = { "#app": makeElement() };
global.document = {
  querySelector: (selector) => {
    if (!store[selector]) store[selector] = makeElement();
    return store[selector];
  },
  querySelectorAll: () => [],
};
// 两个接口共用这份 payload：/history 只取其中的 history 数组
global.fetch = async (url) => ({
  ok: true,
  json: async () => (String(url).includes("/history") ? { data: payload.history } : payload),
});
eval(js);
setTimeout(() => {
  process.stdout.write(JSON.stringify({
    app: store["#app"].innerHTML,
    freshness: store["#freshness"].innerHTML,
    // 成交额图与篮子表渲染在各自的容器里（render 之后由 wire* 填充）
    turnoverChart: store["#turnover-chart"] ? store["#turnover-chart"].innerHTML : "",
    basketTable: store["#basket-table"] ? store["#basket-table"].innerHTML : "",
    heatmap: store["#heatmap"] ? store["#heatmap"].innerHTML : "",
    events: store["#events"] ? store["#events"].innerHTML : "",
    basketFlowChart: store["#basket-flow-chart"] ? store["#basket-flow-chart"].innerHTML : "",
  }));
}, 300);
"""


def _payload() -> dict:
    """最小但字段齐全的一份看盘台返回体。"""
    return {
        "data": {
            "meta": {
                "asof_date": "2026-09-11",
                "quality": "PASS",
                "calculation_version": "pulse_v2",
                "overall_state": "防守",
                "strong_layers": 0,
                "known_layers": 3,
                "quadrant_label": "低位平量：信号不明确",
                "turnover_scope": "沪深两市股票",
                "broad_index": {"index_id": "000300", "name": "沪深300", "position_pct_250d": 0.09},
            },
            "layers": [
                {
                    "key": "liquidity", "label": "① 流动性", "question": "市场有没有钱？",
                    "state": "NEUTRAL", "score": 0, "note": "两融余额 5 日 -0.39%，横盘",
                    "facts": [{"label": "两融余额合计", "value": 2.6e12, "kind": "money"}],
                    "coverage": "沪深两市两融余额", "unavailable": "北向资金",
                },
                {
                    "key": "volume", "label": "② 量能", "question": "钱动没动？",
                    "state": "WEAK", "score": -1, "note": "量比 1.04，平量",
                    "facts": [{"label": "沪市换手率", "value": 1.39, "kind": "rate"}],
                    "coverage": "沪深交易所每日概况", "unavailable": "深市换手率",
                },
                {
                    "key": "etf", "label": "③ 宽基 ETF", "question": "大钱进没进？",
                    "state": "WEAK", "score": -1, "note": "5 日估算净申购 -2.8 亿",
                    "pending": {"from": "WEAK", "to": "NEUTRAL"},
                    "facts": [{"label": "折溢价中位数", "value": 0.0015, "kind": "ratio"}],
                    "coverage": "宽基篮子", "unavailable": "折溢价历史",
                },
            ],
            "transitions": [
                {
                    "trade_date": "2026-09-11", "overall_changed": True,
                    "from_state": "中性观望", "to_state": "防守",
                    "changed_layers": [
                        {"key": "volume", "label": "② 量能", "from": "NEUTRAL", "to": "WEAK",
                         "note": "成交额 19746 亿，量比 1.04，平量"},
                    ],
                    "leading_layer": "volume", "kind": "market",
                    "significance": "量能确认/背离",
                },
                {
                    "trade_date": "2026-07-20", "overall_changed": True,
                    "from_state": "偏多", "to_state": "中性观望",
                    "changed_layers": [
                        {"key": "etf", "label": "③ 宽基 ETF", "from": "UNKNOWN", "to": "NEUTRAL",
                         "note": "篮子 38 只"},
                    ],
                    "leading_layer": "etf", "kind": "coverage",
                    "significance": "数据开始覆盖/中断",
                },
            ],
            "turnover_series": [
                {"trade_date": "2026-09-10", "turnover_amount_total": 1.9e12,
                 "turnover_amount_20d_avg": None, "turnover_rate_pct": 1.39},
                {"trade_date": "2026-09-11", "turnover_amount_total": 1.97e12,
                 "turnover_amount_20d_avg": 1.95e12, "turnover_rate_pct": 1.39},
            ],
            "margin_series": [
                {"trade_date": "2026-09-10", "margin_balance_total": 2.63e12},
                {"trade_date": "2026-09-11", "margin_balance_total": 2.64e12},
            ],
            "activity": {
                "trade_date": "2026-09-11", "rising_count": 604, "falling_count": 4567,
                "flat_count": 36, "limit_up_count": 40, "limit_down_count": 21,
                "suspended_count": 12, "activity_pct": 11.57,
                "statistic_at": "2026-09-11T15:00:00",
            },
            "valuation": {
                "trade_date": "2026-09-11", "pe_ttm_median": 36.37, "pe_lyr_median": 38.3,
                "quantile_ttm_median_all_history": 0.5, "quantile_ttm_median_10y": 0.65,
                "metric_basis": "lg_stock_a_ttm_lyr",
            },
            "index_valuations": [
                {"index_id": "000300", "index_name": "沪深300", "trade_date": "2026-09-11",
                 "pe_ttm": 12.8, "pe_ttm_percentile_all_history": 0.65,
                 "pe_ttm_percentile_10y": 0.67, "observations_all_history": 258},
            ],
            "quadrant_points": [
                {"trade_date": f"2026-08-{day:02d}", "position_pct_250d": 0.1 + day / 100,
                 "volume_ratio_5d": 0.9 + day / 100, "turnover_amount_total": 1.9e12,
                 "quadrant_label": "低位放量：吸筹/启动，重点跟踪"}
                for day in range(1, 21)
            ],
            "fund_issuance": {
                "monthly": [
                    {"month": "2026-07", "fund_count": 101, "raised_shares_total": 270.86,
                     "missing_scale_count": 3},
                    {"month": "2026-08", "fund_count": 75, "raised_shares_total": 119.02,
                     "missing_scale_count": 1},
                ],
                "recent_3m_raised_shares": 1237.26,
                "previous_3m_raised_shares": 3497.22,
                "change_pct": -64.63,
                "latest_complete_month": "2026-08",
                "current_month": "2026-09",
                "basis": "fund_new_found_em",
                "unit": "亿元（募集份额）",
            },
            "freshness": [
                {"dataset": "市场成交额", "asof_date": "2026-09-11", "lag_trading_days": 0},
                {"dataset": "两融余额", "asof_date": "2026-09-10", "lag_trading_days": 1},
            ],
            "basket": [
                {
                    "security_id": "510300.SH", "short_name": "华泰柏瑞沪深300ETF",
                    "index_id": "000300", "index_name": "沪深300指数",
                    "estimated_aum": 1.07e11, "net_subscription_5d": 9.06e7,
                    "net_subscription_20d": -6.7e8, "premium_pct": 0.0015,
                    "turnover_amount": 4.4e9, "change_pct": -1.69,
                },
                {
                    "security_id": "159915.SZ", "short_name": "创业板ETF易方达",
                    "index_id": "399006", "index_name": "创业板指",
                    "estimated_aum": 6.6e10, "net_subscription_5d": None,
                    "net_subscription_20d": None, "premium_pct": None,
                    "turnover_amount": 6.3e9, "change_pct": 0.51,
                },
            ],
            "basket_flow": {
                "metric": "estimated_net_subscription_1d",
                "calculation_version": "flow_v1",
                "unit": "元",
                "window": {"start": "2026-09-10", "end": "2026-09-11"},
                "skipped_index_names": ["科创50", "创业板指"],
                "series": [
                    {
                        "index_id": "000300", "index_name": "沪深300",
                        "member_count": 2, "contributor_count": 2,
                        "start_date": "2026-09-10", "end_date": "2026-09-11",
                        "cumulative_net_subscription": 4.0e8,
                        "points": [
                            {"trade_date": "2026-09-10", "daily_net_subscription": 1.0e8,
                             "cumulative_net_subscription": 1.0e8, "contributor_count": 2},
                            {"trade_date": "2026-09-11", "daily_net_subscription": 3.0e8,
                             "cumulative_net_subscription": 4.0e8, "contributor_count": 2},
                        ],
                    },
                ],
            },
            "gaps": ["成交额口径为沪深两市股票，不含北交所。"],
        },
        "meta": {"asof_date": "2026-09-11", "quality": "PASS", "calculation_version": "pulse_v2"},
        "errors": [],
        # /api/v1/watchboard/history 的返回体（状态热力图用）
        "history": [
            {
                "trade_date": "2026-09-10", "liquidity_state": "NEUTRAL",
                "volume_state": "WEAK", "etf_state": "NEUTRAL", "overall_state": "防守",
                # 原始信号已转、确认还没跟上：热力图上应标记为"待确认"
                "volume_raw_state": "NEUTRAL", "etf_raw_state": "NEUTRAL",
                "liquidity_raw_state": "NEUTRAL",
                "liquidity_note": "两融余额 5 日 +0.12%，横盘",
                "volume_note": "成交额 18000 亿，量比 0.92，缩量",
                "etf_note": "5 日估算净申购 -1.0 亿",
            },
            {
                "trade_date": "2026-09-11", "liquidity_state": "NEUTRAL",
                "volume_state": "WEAK", "etf_state": "WEAK", "overall_state": "防守",
                "volume_raw_state": "WEAK", "etf_raw_state": "WEAK",
                "liquidity_raw_state": "NEUTRAL",
                "liquidity_note": "两融余额 5 日 -0.39%，横盘",
                "volume_note": "成交额 19746 亿，量比 1.04，平量",
                "etf_note": "5 日估算净申购 -2.8 亿",
            },
        ],
    }


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("未安装 Node，跳过前端渲染回归测试")
    tmp = tmp_path_factory.mktemp("frontend")
    payload_path = tmp / "payload.json"
    payload_path.write_text(json.dumps(_payload(), ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [node, "-e", RUNNER, str(WEB_ROOT / "watchboard.html"), str(payload_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_render_has_no_placeholder_values(rendered):
    app = rendered["app"] + rendered["basketTable"] + rendered["turnoverChart"]
    assert app, "页面没有渲染出内容"
    assert "undefined" not in app
    assert "NaN" not in app
    assert "[object Object]" not in app


def test_units_are_rendered_per_metric(rendered):
    table = rendered["basketTable"]
    assert table, "篮子表没有渲染"
    # 涨跌幅是百分数（-1.69 → -1.69%），折溢价是比例（0.0015 → +0.15%）
    assert "-1.69%" in table
    assert "+0.15%" in table
    assert "-169.00%" not in table
    # 换手率是水平值，不能带正负号
    assert "+1.39%" not in rendered["app"]


def test_freshness_and_interactive_blocks_are_present(rendered):
    app = rendered["app"]
    assert "三层状态历史" in app
    assert "量价四象限" in app
    assert 'id="turnover-chart"' in app
    assert 'id="basket-table"' in app
    assert 'id="basket-filters"' in app
    assert 'id="basket-flow-chart"' in app
    assert rendered["turnoverChart"], "成交额图没有渲染"
    assert rendered["basketTable"].count("<tr") >= 2, "篮子表没有数据行"
    # 热力图：5 行（边际变化 + 三层 + 综合结论）× 2 天
    assert rendered["heatmap"].count('class="hm-cell') == 10
    assert 'data-state="WEAK"' in rendered["heatmap"]
    # 边际变化标记：结论切换 + 待确认（原始信号已变）
    assert 'data-kind="overall"' in rendered["heatmap"]
    assert 'data-kind="pending"' in rendered["heatmap"]
    # 待确认徽标出现在卡片上
    assert "原始信号转NEUTRAL，待确认" in app
    # 事件列表：只列 market 事件，数据覆盖事件不算市场事件
    assert rendered["events"].count('class="event"') == 1
    assert "量能确认/背离" in rendered["events"]
    assert "数据开始覆盖/中断" not in rendered["events"]
    # 新增面板：资金/量能归一化对比 + 新发基金月度
    assert "资金 vs 量能：归一化对比" in app
    assert "新发基金成立规模（月度）" in app
    assert "1237.3 亿" in app  # 近 3 个完整月（亿元，不是元）
    assert "-64.63%" in app
    # 篮子净申购累积：曲线 + 明细表 + 覆盖率标注
    # 曲线内联在 #app 的模板里（wireBasketFlow 只挂交互）
    assert app.count('class="flow-line"') == 1
    assert "篮子净申购累积（按跟踪指数）" in app
    assert "2 / 2 只" in app
    assert "科创50、创业板指 目前完全没有日度数据" in app
    assert "滞后 1 个交易日" in rendered["freshness"]
    assert "当日" in rendered["freshness"]
