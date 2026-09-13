# V2.1 总体验收（Case A–E）

> 由 `python scripts/v2_1_acceptance.py --write-doc` 生成，可重复执行。
>
> commit `6c328d9` ｜ as-of `2026-09-11` ｜ 生成时间 2026-09-13 18:42
>
> 总状态：**PASS**

## 1. Case A–D（每项都对应一段可执行的最小验证）

| Case | 结论 | 内容 | 验证 | 耗时 |
| --- | --- | --- | --- | --- |
| A | ✅ PASS | 515880 拆分：metric_v2 收益/回撤、flow_v2、tracking 不再出现假 -50% / 假巨额申赎 | `tests/integration/test_corporate_action_pipeline.py::test_split_no_longer_creates_fake_returns_or_subscriptions`, `tests/integration/test_corporate_action_pipeline.py::test_adjusted_series_is_point_in_time_safe`, `tests/integration/test_corporate_action_pipeline.py::test_audit_flags_unadjusted_flow_across_a_split` | 9.2s |
| B | ✅ PASS | 现金分红：adjusted_shares 不变，flow_v2 不制造假赎回，净值收益保持连续 | `tests/integration/test_corporate_action_pipeline.py::test_cash_dividend_does_not_create_a_fake_redemption`, `tests/integration/test_corporate_action_pipeline.py::test_cash_dividend_keeps_nav_returns_continuous` | 6.9s |
| C | ✅ PASS | 同日 v1/v2 并存：普通 Compare 稳定返回 v2（重复 100 次结果一致） | `tests/integration/test_version_routing.py::test_compare_uses_the_production_version`, `tests/integration/test_version_routing.py::test_screen_uses_the_production_version`, `tests/integration/test_version_routing.py::test_repeated_compare_is_byte_for_byte_stable` | 6.7s |
| D | ✅ PASS | 历史 Point-in-Time：Tag / Holdings / Peer / Tracking / Profile 不回看未来 | `tests/integration/test_pit_tags.py`, `tests/integration/test_pit_holdings.py`, `tests/integration/test_pit_peer.py`, `tests/integration/test_pit_profile.py` | 3.8s |

各 Case 的 pytest 末行输出：

- **Case A**：`...                                                                      [100%]`
- **Case B**：`..                                                                       [100%]`
- **Case C**：`...                                                                      [100%]`
- **Case D**：`.............                                                            [100%]`

## 2. Case E — GitHub Actions

- 普通 CI（`.github/workflows/ci.yml`）：**success**
- 依据：https://github.com/jinking/etf-lens/actions/runs/34749998153（head 2b87495）

live 上游用例只在 `.github/workflows/live-smoke.yml` 跑，不阻塞 PR；
普通 CI 用 `pytest -q -m "not live"`，保证干净环境可复现。

## 3. 总体验收（研究链路，非测试）

```text
python scripts/v2_acceptance.py --asof 2026-09-11 --write-doc
```

产物：`docs/V2_ACCEPTANCE.md`（国产算力 ETF · Point-in-Time 全链路）。
历史 regime 验证报告：`etf validate-pulse --write-doc` → `docs/REGIME_VALIDATION.md`。

## 4. 结论边界

- Case A–D 是**确定性回归**：同样的库、同样的 as-of，重复执行必须同样通过；
- Case E 依赖外部 CI 服务，本地只能查到「最近一次」，不替代 CI 本身的结论；
- 本文件覆盖「正确性」，不覆盖「行情观点」——系统不产出买卖建议。
