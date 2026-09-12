from collections.abc import Callable

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
