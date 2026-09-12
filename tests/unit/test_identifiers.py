import pytest

from etf_engine.domain.identifiers import SecurityId


def test_parse_sse_canonical():
    assert SecurityId.parse("588200.SH").value == "588200.SH"


def test_parse_szse_canonical():
    assert SecurityId.parse("159915.SZ").value == "159915.SZ"


def test_infer_exchange_for_common_etf_codes():
    assert SecurityId.parse("588200").value == "588200.SH"
    assert SecurityId.parse("159915").value == "159915.SZ"


def test_unknown_code_requires_canonical_exchange():
    with pytest.raises(ValueError):
        SecurityId.parse("999999")
