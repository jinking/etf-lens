"""把基金"业绩比较基准"文本对齐到指数目录。

这是"事实对齐"而不是"语义猜测"：只有基准文本里精确包含某个指数名称时才命中；
命中不唯一或命中不了就返回 None，由调用方记录质量问题，
绝不用看起来最相似的名称凑一个。
"""

import re
from dataclasses import dataclass

#: 基准文本里常见的修饰词，去掉后不携带指数身份信息。
BENCHMARK_DECORATIONS = (
    "收益率",
    "全收益",
    "净收益",
    "价格指数",
    "人民币",
    "美元",
    "港元",
)

_SEPARATORS = re.compile(r"[\s,，、;；/··]+")
_BRACKETS = re.compile(r"[（）()\[\]【】]")

#: 名称太短时容易误命中（例如"上证"），低于该长度不参与匹配。
MIN_NAME_LENGTH = 4


def normalize_index_name(value: str) -> str:
    """归一化指数名称/基准文本，用于保守匹配。"""
    text = str(value).strip()
    if not text:
        return ""
    for decoration in BENCHMARK_DECORATIONS:
        text = text.replace(decoration, "")
    text = _BRACKETS.sub("", text)
    text = _SEPARATORS.sub("", text)
    return text.upper()


@dataclass(frozen=True, slots=True)
class IndexMatch:
    index_id: str
    index_name: str
    normalized_benchmark: str


def match_index(benchmark: str, catalog: dict[str, list[str]]) -> IndexMatch | None:
    """在目录里寻找唯一的指数名称命中。

    ``catalog`` 形如 ``{index_id: [指数全称, 指数简称, ...]}``。
    """
    normalized_benchmark = normalize_index_name(benchmark)
    if not normalized_benchmark:
        return None

    candidates: dict[str, tuple[str, str]] = {}
    for index_id, names in catalog.items():
        for name in names:
            normalized_name = normalize_index_name(name)
            if len(normalized_name) < MIN_NAME_LENGTH:
                continue
            if normalized_name in normalized_benchmark:
                # 同一条指数可能同时命中全称与简称，取更长的那个。
                current = candidates.get(index_id)
                if current is None or len(normalized_name) > len(current[0]):
                    candidates[index_id] = (normalized_name, name)

    if len(candidates) != 1:
        # 0 个：基准里没有对应指数；多个：基准文本不足以唯一定位。
        # 两种情况都必须交给调用方记录，而不是挑一个看起来最像的。
        return None

    index_id, (_, name) = next(iter(candidates.items()))
    return IndexMatch(
        index_id=index_id,
        index_name=name,
        normalized_benchmark=normalized_benchmark,
    )
