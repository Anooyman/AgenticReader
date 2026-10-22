"""
路径安全校验工具

提供统一的路径拼接校验功能，防止调用方传入的名称通过
目录穿越（如 ".." 或 "../../etc"）访问或删除数据目录之外的内容。

参考 data.py 删除源 PDF 时已有的正确校验实现，
将同类防御收敛到一处，供各 API 的 BASE / doc_name 拼接复用。
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 允许被安全剥离的后缀：校验的是剥离后的名称部分
_STRIPPABLE_SUFFIXES = (".pdf",)


def normalize_doc_name(doc_name: str) -> str:
    """
    规范化文档名称：去除首尾空白，并在结尾出现已知后缀时剥离它。

    这样 "foo.pdf" 与 "foo" 会落到同一个目录 / 文件基名，
    与仓库各处既有的 `name.replace('.pdf', '')` 行为保持一致，
    但只在结尾剥离一次，避免误删名称中间的内容。

    Args:
        doc_name: 原始文档名称

    Returns:
        剥离后缀并去除空白后的名称
    """
    name = str(doc_name).strip()
    lowered = name.lower()
    for suffix in _STRIPPABLE_SUFFIXES:
        if lowered.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def safe_path(base: Path, name: str) -> Path:
    """
    将调用方传入的名称安全地拼接到基目录 base 之下。

    校验规则：
      - 拒绝空名称
      - 拒绝包含路径分隔符（"/" 或 "\\"）的名称
      - 拒绝以点开头的名称
      - 允许去掉 .pdf 等已知后缀后再校验
      - resolve() 之后断言结果仍位于 base 之内，越界即拒绝

    Args:
        base: 基目录（数据目录等）
        name: 调用方传入的文档名称

    Returns:
        经过校验、已解析的绝对路径

    Raises:
        ValueError: 名称非法或解析后越出 base 目录（带中文信息）
    """
    raw = str(name)

    if not raw.strip():
        raise ValueError("非法名称：名称不能为空")

    if "/" in raw or "\\" in raw:
        raise ValueError(f"非法名称：包含路径分隔符: {name}")

    # 允许去掉 .pdf 后缀后再做名称合法性判断
    base_name = normalize_doc_name(raw)

    if not base_name:
        raise ValueError(f"非法名称：剥离后缀后为空: {name}")

    if base_name.startswith("."):
        raise ValueError(f"非法名称：不能以点开头: {name}")

    try:
        base_resolved = Path(base).resolve()
        candidate = (Path(base) / base_name).resolve()
    except (OSError, ValueError) as e:
        raise ValueError(f"非法名称：路径解析失败: {name} ({e})")

    # 断言解析后的结果仍位于 base 之内，否则视为目录穿越
    if not candidate.is_relative_to(base_resolved):
        raise ValueError(f"非法名称：路径越界，不在基目录内: {name}")

    return candidate
