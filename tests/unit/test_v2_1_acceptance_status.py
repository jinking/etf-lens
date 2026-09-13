"""V2.1 总体验收门禁状态单元测试。

验证规则：
1. A-D PASS + CI success + same SHA → PASS
2. A-D PASS + CI failure → FAIL
3. A-D PASS + CI UNKNOWN → PARTIAL（默认不允许 UNKNOWN 冒充 PASS）
4. A-D PASS + CI UNKNOWN + allow_ci_unknown → PASS（显式放宽）
5. A-D PASS + CI success but old SHA → PARTIAL (CI=STALE)
6. A-D FAIL + CI success → FAIL
7. A-D PASS + skip_ci → PARTIAL
"""

from scripts.v2_1_acceptance import compute_acceptance_status


def test_status_all_pass_with_current_ci():
    overall, ci_eff = compute_acceptance_status(
        local_pass=True,
        ci_status="success",
        current_sha="1a7298c",
        ci_head_sha="1a7298c123456789",
    )
    assert overall == "PASS"
    assert ci_eff == "SUCCESS"


def test_status_ci_failure_yields_fail():
    overall, _ = compute_acceptance_status(
        local_pass=True,
        ci_status="failure",
        current_sha="1a7298c",
        ci_head_sha="1a7298c123456789",
    )
    assert overall == "FAIL"


def test_status_ci_unknown_yields_partial_by_default():
    overall, ci_eff = compute_acceptance_status(
        local_pass=True,
        ci_status="UNKNOWN",
        current_sha="1a7298c",
        ci_head_sha=None,
    )
    assert overall == "PARTIAL"
    assert ci_eff == "UNKNOWN"


def test_status_ci_unknown_allowed_when_explicitly_flagged():
    overall, _ = compute_acceptance_status(
        local_pass=True,
        ci_status="UNKNOWN",
        current_sha="1a7298c",
        ci_head_sha=None,
        allow_ci_unknown=True,
    )
    assert overall == "PASS"


def test_status_old_sha_yields_stale_and_partial():
    overall, ci_eff = compute_acceptance_status(
        local_pass=True,
        ci_status="success",
        current_sha="1a7298c",
        ci_head_sha="c808026abcdef",
    )
    assert overall == "PARTIAL"
    assert ci_eff == "STALE"


def test_status_local_fail_yields_fail_even_if_ci_success():
    overall, _ = compute_acceptance_status(
        local_pass=False,
        ci_status="success",
        current_sha="1a7298c",
        ci_head_sha="1a7298c",
    )
    assert overall == "FAIL"


def test_status_skip_ci_yields_partial():
    overall, ci_eff = compute_acceptance_status(
        local_pass=True,
        ci_status="UNKNOWN",
        current_sha="1a7298c",
        ci_head_sha=None,
        skip_ci=True,
    )
    assert overall == "PARTIAL"
    assert ci_eff == "SKIPPED"
