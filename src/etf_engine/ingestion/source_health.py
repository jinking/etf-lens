from collections.abc import Iterator
from contextlib import contextmanager

from etf_engine.repositories.source_health_repository import SourceHealthRepository


@contextmanager
def track_source_health(source: str, capability: str) -> Iterator[None]:
    """记录一次上游调用的成败到 ``ops.source_health``。

    用法::

        with track_source_health("sse", "etf_share"):
            shares = source.fetch_shares()

    异常照常向上抛出，只是顺带把健康度记下来。
    """
    repository = SourceHealthRepository()
    try:
        yield
    except Exception as exc:
        try:
            repository.record_failure(source, capability, str(exc))
        except Exception:
            # 健康度记录失败不能掩盖真正的上游错误。
            pass
        raise
    else:
        try:
            repository.record_success(source, capability)
        except Exception:
            pass
