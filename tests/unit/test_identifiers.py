import pytest

from etf_engine.domain.enums import Exchange
from etf_engine.domain.identifiers import SecurityId


def test_parse_sse_canonical():
    assert SecurityId.parse("588200.SH").value == "588200.SH"


def test_parse_szse_canonical():
    assert SecurityId.parse("159915.SZ").value == "159915.SZ"


def test_infer_exchange_for_common_etf_codes():
    assert SecurityId.parse("588200").value == "588200.SH"
    assert SecurityId.parse("159915").value == "159915.SZ"


def test_five_digit_code_is_hong_kong_not_shenzhen():
    """5 位港股代码绝不能被补零成深市 A 股代码。

    历史实现把 01801（信达生物）写成 001801.SZ，与真实存在的深市代码静默合并。
    """
    parsed = SecurityId.parse("01801")

    assert parsed.exchange is Exchange.HKEX
    assert parsed.value == "01801.HK"


def test_hong_kong_suffix_pads_to_five_digits():
    assert SecurityId.parse("700.HK").value == "00700.HK"
    assert SecurityId.parse("01801.hk").value == "01801.HK"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("920002", "920002.BJ"),
        ("430047", "430047.BJ"),
        ("830799", "830799.BJ"),
        ("871981", "871981.BJ"),
        ("900901", "900901.SH"),
        ("200011", "200011.SZ"),
    ],
)
def test_beijing_and_b_share_codes_are_recognized(code, expected):
    assert SecurityId.parse(code).value == expected


def test_beijing_suffix_is_accepted():
    assert SecurityId.parse("920002.bj").value == "920002.BJ"


@pytest.mark.parametrize("code", ["999999", "4", "abc", "", "   "])
def test_unknown_code_requires_canonical_exchange(code):
    with pytest.raises(ValueError):
        SecurityId.parse(code)


def test_unsupported_suffix_is_rejected():
    with pytest.raises(ValueError):
        SecurityId.parse("588200.XX")
