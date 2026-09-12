"""上游调用必须有超时兜底，否则卡住会把整条链路挂死。"""

import socket

import pytest

from etf_engine.ingestion.retry import socket_timeout
from etf_engine.sources.akshare import index_data


def test_socket_timeout_sets_and_restores_the_default():
    original = socket.getdefaulttimeout()

    with socket_timeout(5):
        assert socket.getdefaulttimeout() == 5

    assert socket.getdefaulttimeout() == original


def test_socket_timeout_restores_even_on_error():
    original = socket.getdefaulttimeout()

    with pytest.raises(RuntimeError), socket_timeout(3):
        raise RuntimeError("boom")

    assert socket.getdefaulttimeout() == original


def test_csindex_quote_fetch_passes_an_explicit_timeout(monkeypatch):
    captured: dict = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [["2026-09-11"] + ["x"] * 15]}

    def _fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(index_data.requests, "get", _fake_get)

    from datetime import date

    frame = index_data.fetch_csindex_quotes(
        "931160", start_date=date(2026, 9, 1), end_date=date(2026, 9, 11)
    )

    assert captured["timeout"] == 20.0, "必须显式传 timeout，不能依赖第三方默认值"
    assert captured["params"]["indexCode"] == "931160"
    assert list(frame.columns)[0] == "日期"


def test_csindex_quote_fetch_rejects_unexpected_shape(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [["只有两列", "x"]]}

    monkeypatch.setattr(index_data.requests, "get", lambda *a, **k: _Response())

    from datetime import date

    with pytest.raises(RuntimeError):
        index_data.fetch_csindex_quotes(
            "931160", start_date=date(2026, 9, 1), end_date=date(2026, 9, 11)
        )
