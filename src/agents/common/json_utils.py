"""
LLM 响应 JSON 清洗（跨 agent 唯一实现）

收敛前，"从 LLM 返回文本里抠出 JSON" 这件事在仓库里有四套各写一遍的实现，
能力与失败语义互不一致：

1. ``src/agents/search/utils.py`` 的 ``extract_json_from_llm_response``
   —— 唯一会剥 ```json / ``` markdown 围栏的版本，失败抛 ``json.JSONDecodeError``；
2. ``src/agents/indexing/components/metadata_extractor.py`` 的
   ``_parse_metadata_response`` —— ``re.search(r'\\{.*\\}', DOTALL)`` 贪婪首尾截取，
   截不到再对整串裸 ``json.loads``，失败返回 ``{}``；
3. ``src/agents/retrieval/nodes.py`` think 节点 —— 仅当
   ``response.strip().startswith('{')`` 时裸 ``json.loads``，否则给 ``None``；
4. ``src/agents/retrieval/nodes.py`` evaluate 节点 —— 同上，但给 ``{}``。

本模块取三者清洗能力的**并集**收敛成一个入口 :func:`parse_llm_json`：
围栏剥离 + 首尾括号截取 + 逐候选解析；**任何解析失败都返回 ``default``，不抛异常**。
调用方原本依赖的失败语义（抛 JSONDecodeError / 返回 None / 返回 {}）由各调用点
用 ``default`` 参数（必要时补一行显式 raise）原地保住。

清洗候选按优先级排列，"先成功者赢"，因此对任何原本能解析成功的输入，
返回值与原实现逐字一致（向后兼容）；只有在原实现会失败的输入上才会多救回来。
"""

from __future__ import annotations

from typing import Any, Iterator, List
import json
import logging

logger = logging.getLogger(__name__)

__all__ = ["PARSE_FAILED", "parse_llm_json"]


class _ParseFailed:
    """显式"没解析出来"哨兵。

    ``default=None`` 在"解析失败"与"LLM 真的返回了 null"之间无法区分；
    需要用 raise / 分支区分这两者的调用点，传 ``default=PARSE_FAILED`` 即可。
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<PARSE_FAILED>"


PARSE_FAILED = _ParseFailed()

_FENCE_JSON = "```json"
_FENCE = "```"

# expect 允许的取值（同时接受内置类型 dict/list，写起来更顺手）
_EXPECT_DICT = "dict"
_EXPECT_LIST = "list"
_EXPECT_ANY = "any"


def _normalize_expect(expect: Any) -> str:
    """把 expect 归一成 'dict' / 'list' / 'any'；无法识别的值按 'any' 处理。"""
    if expect is None:
        return _EXPECT_ANY
    if expect is dict:
        return _EXPECT_DICT
    if expect is list:
        return _EXPECT_LIST
    if isinstance(expect, str):
        value = expect.strip().lower()
        if value in (_EXPECT_DICT, _EXPECT_LIST, _EXPECT_ANY):
            return value
    return _EXPECT_ANY


def _matches_expect(parsed: Any, expect: str) -> bool:
    if expect == _EXPECT_DICT:
        return isinstance(parsed, dict)
    if expect == _EXPECT_LIST:
        return isinstance(parsed, list)
    return True


def _strip_code_fence(text: str) -> str:
    """
    剥掉 markdown 代码块围栏（对齐原 search/utils.py 的实现）。

    - 优先取 ```json ... ``` 之间的内容；
    - 没有 ```json 时退化为取第一个 ``` ... ``` 代码块，并跳过语言标识行；
    - 找不到闭合围栏时原样返回（原实现同样是"找不到就不动"）。
    """
    if _FENCE_JSON in text:
        start = text.find(_FENCE_JSON) + len(_FENCE_JSON)
        end = text.find(_FENCE, start)
        if end != -1:
            return text[start:end].strip()
        return text

    if _FENCE in text:
        start = text.find(_FENCE) + len(_FENCE)
        # 跳过可能的语言标识符（如 json、python 等）
        newline_pos = text.find("\n", start)
        if newline_pos != -1:
            start = newline_pos + 1
        end = text.find(_FENCE, start)
        if end != -1:
            return text[start:end].strip()

    return text


def _bracket_slices(text: str) -> Iterator[str]:
    """
    首尾括号截取（对齐原 metadata_extractor 的 ``re.search(r'\\{.*\\}', DOTALL)`` 语义：
    第一个开括号到最后一个闭括号的贪婪片段）。先试对象再试数组。
    """
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        first = text.find(open_ch)
        last = text.rfind(close_ch)
        if first != -1 and last != -1 and last > first:
            yield text[first:last + 1]


def _candidates(text: str) -> List[str]:
    """
    生成去重后的解析候选串，按优先级排列。

    整串永远排在第一，这样"纯 JSON 但字符串值里恰好含三个反引号"的响应
    不会被围栏剥离误伤（原 search/utils 版本会，属于被顺手修掉的隐患）。
    """
    candidates: List[str] = []

    stripped = text.strip()
    if stripped:
        candidates.append(stripped)

        fenced = _strip_code_fence(stripped)
        if fenced != stripped and fenced:
            candidates.append(fenced)

        for source in (stripped, fenced):
            if not source:
                continue
            for slice_ in _bracket_slices(source):
                candidates.append(slice_)

    # 保序去重
    unique: List[str] = []
    seen = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def parse_llm_json(
    text: Any,
    *,
    default: Any = None,
    expect: Any = _EXPECT_ANY,
) -> Any:
    """
    从 LLM 返回文本中解析出 JSON 值。

    清洗顺序（各历史实现的并集）：
    1. 整串直接 ``json.loads``（快路径，等价于各实现的裸 loads）；
    2. 剥 ```json / ``` markdown 围栏后再试；
    3. 首尾大括号 / 方括号截取后再试（吃掉前后缀杂文本、解说语）。

    Args:
        text: LLM 响应文本。非字符串（含 ``None``）直接返回 ``default``。
        default: 解析失败时的返回值；**本函数不抛异常**。
        expect: 期望的顶层类型，``dict`` / ``list`` / ``any``（也可直接传
            ``dict`` / ``list`` 内置类型）。类型不符按解析失败处理，继续尝试
            后续候选，全部不符则返回 ``default``。

    Returns:
        解析出的 dict / list / 任意 JSON 值，失败时返回 ``default``。
    """
    if not isinstance(text, str):
        return default

    want = _normalize_expect(expect)

    for candidate in _candidates(text):
        try:
            parsed = json.loads(candidate)
        except Exception as e:  # JSONDecodeError 之外的任何意外都不该冒泡到业务分支
            logger.debug(f"🔧 [parse_llm_json] 候选解析失败（忽略）: {e}")
            continue
        if _matches_expect(parsed, want):
            return parsed

    logger.debug(
        f"🔧 [parse_llm_json] 未能从 LLM 响应中解析出 JSON"
        f"（expect={want}，返回 default）: {text[:200]!r}"
    )
    return default
