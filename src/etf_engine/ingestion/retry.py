import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

#: 上游抖动导致的瞬时失败，值得重试。
TRANSIENT_EXCEPTIONS = (ConnectionError, TimeoutError, OSError)


def with_retry[T](
    call: Callable[[], T],
    *,
    attempts: int = 3,
    base_wait: float = 0.4,
    max_wait: float = 4.0,
) -> T:
    """对瞬时性网络错误做指数退避重试。

    用于逐只基金/逐日期的回补任务：单点抖动不应该让整个批次失败。
    业务性异常（解析失败、参数错误）不会被重试。
    """
    retrying = retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=base_wait, max=max_wait),
        retry=retry_if_exception_type(TRANSIENT_EXCEPTIONS),
    )(call)
    try:
        return retrying()
    except RetryError:  # pragma: no cover - reraise=True 时不会走到
        raise


@contextmanager
def socket_timeout(seconds: float = 20.0) -> Iterator[None]:
    """给没有自带超时的第三方调用兜底。

    AKShare 的不少包装函数内部是裸 ``requests.get``，不带 ``timeout``：
    上游卡住时，整个同步链路会无限期挂起（实测出现过 13 分钟不返回）。
    这里设置 socket 默认超时，退出时恢复原值。
    """
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(seconds)
    try:
        yield
    finally:
        socket.setdefaulttimeout(previous)
