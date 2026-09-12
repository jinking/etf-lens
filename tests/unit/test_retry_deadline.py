"""上游超时兜底的测试。

背景：``socket.setdefaulttimeout`` 约束不了 ``requests`` 连接池里复用的连接，
实测导致同步链路挂死二十分钟。这里锁定"到点必须返回"这条行为。
"""

import time

import pytest

from etf_engine.ingestion.retry import call_with_deadline, socket_timeout, with_retry


def test_call_with_deadline_returns_value():
    assert call_with_deadline(lambda: 42, timeout=1.0) == 42


def test_call_with_deadline_raises_timeout_and_does_not_block():
    started = time.monotonic()

    def _hang():
        time.sleep(30)

    with pytest.raises(TimeoutError):
        call_with_deadline(_hang, timeout=0.2)

    # 不能等到上游返回：必须按 timeout 到点就抛
    assert time.monotonic() - started < 5


def test_call_with_deadline_propagates_original_exception():
    def _boom():
        raise ValueError("上游解析失败")

    with pytest.raises(ValueError, match="上游解析失败"):
        call_with_deadline(_boom, timeout=1.0)


def test_deadline_timeout_is_retryable():
    attempts = {"count": 0}

    def _hang():
        attempts["count"] += 1
        time.sleep(30)

    with pytest.raises(TimeoutError):
        with_retry(lambda: call_with_deadline(_hang, timeout=0.1), attempts=2, base_wait=0.01)

    # TimeoutError 属于瞬时错误，应当被重试而不是直接放弃
    assert attempts["count"] == 2


def test_socket_timeout_restores_previous_default():
    import socket

    previous = socket.getdefaulttimeout()
    with socket_timeout(5.0):
        assert socket.getdefaulttimeout() == 5.0
    assert socket.getdefaulttimeout() == previous
