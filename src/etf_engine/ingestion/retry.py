import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import cast

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

    注意：``socket.setdefaulttimeout`` 只约束**新建**的 socket。``requests``
    的连接池会把在超时上下文之外建立的连接复用进来，这类连接上的阻塞读
    永远不会超时（实测：看盘台回补卡住 20 分钟，lsof 显示一条 ESTABLISHED
    的 https 连接）。需要硬保证的调用请用 :func:`call_with_deadline`。
    """
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(seconds)
    try:
        yield
    finally:
        socket.setdefaulttimeout(previous)


def call_with_deadline[T](call: Callable[[], T], *, timeout: float) -> T:
    """在守护线程里执行调用，超时即放弃并抛 ``TimeoutError``。

    这是"上游不返回"的唯一可靠兜底：连接池复用的连接不理会 socket 默认超时，
    只有把调用丢到单独线程、由主线程 ``join(timeout)`` 才能保证到点返回。

    超时后那个线程会被放弃（daemon，不阻塞进程退出）。因此调用方应当
    **限制重试次数**，避免悬挂线程堆积；单点失败按既有约定记入
    ``ops.quality_issue`` 后继续处理下一条数据。
    """
    outcome: dict = {}

    def _target() -> None:
        try:
            outcome["value"] = call()
        except BaseException as exc:  # noqa: BLE001 - 原样回传给调用方
            outcome["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"上游调用超过 {timeout}s 未返回")
    if "error" in outcome:
        raise outcome["error"]
    return cast(T, outcome["value"])
