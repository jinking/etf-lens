"""上游数据契约检查：把"shape 变了"变成一条可追溯的问题，而不是 KeyError。

每个外部数据源都至少要能回答：

```text
required columns   必需列在不在
empty response     返回体是不是空的（空 ≠ 没数据，也可能是接口变了）
unexpected schema  形状是否符合预期
timeout            有没有超时兜底（见 ingestion/retry.py: socket_timeout）
stale date         数据日期是否明显落后
```

前四项在本模块；超时在 retry 模块；"是否陈旧"由各适配器/任务按业务判断
（例如份额快照日期）。所有失败都产出 :class:`DataQualityIssue`，由任务写进
``ops.quality_issue``。
"""

from dataclasses import dataclass

import pandas as pd

from etf_engine.domain.quality import DataQualityIssue, error, warn


@dataclass(frozen=True, slots=True)
class FrameContract:
    """一张上游表的形状契约。"""

    dataset: str
    required_columns: tuple[str, ...]
    #: 允许为空表吗？（允许时"空"只记 WARN，不允许时空表算 ERROR）
    allow_empty: bool = False


def check_frame(
    frame: pd.DataFrame | None, contract: FrameContract
) -> tuple[bool, list[DataQualityIssue]]:
    """检查返回体是否符合契约，返回 ``(是否可用, 问题列表)``。"""
    issues: list[DataQualityIssue] = []

    if frame is None:
        issues.append(error(f"{contract.dataset}_response_none", "上游返回体为 None"))
        return False, issues
    if frame.empty:
        if contract.allow_empty:
            issues.append(warn(f"{contract.dataset}_empty_response", "上游返回空表"))
            return False, issues
        issues.append(error(f"{contract.dataset}_empty_response", "上游返回空表（接口可能已变）"))
        return False, issues

    missing = [column for column in contract.required_columns if column not in frame.columns]
    if missing:
        issues.append(
            error(
                f"{contract.dataset}_schema_changed",
                f"缺少必需列 {missing}；实际列={list(frame.columns)[:12]}",
            )
        )
        return False, issues
    return True, issues
