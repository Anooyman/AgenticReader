"""
进度上报（跨 agent 唯一实现）

收敛前 ``_send_progress`` 有三份几乎一样的实现：

- ``src/agents/answer/tools.py``  —— payload 6 个字段；
- ``src/agents/answer/nodes.py``  —— 同上，末尾多一次 ``progress_data.update(kwargs)``；
- ``src/agents/retrieval/nodes.py`` —— 多一个 ``state`` 参数，据此补
  ``iteration`` / ``max_iterations``，另外支持可选的 ``tool`` 字段。

三份的骨架完全相同：**回调判空 → 组 payload → await 回调 → 异常就地吞掉只打
warning**。本模块把这段骨架收敛为 :func:`emit_progress`，字段拼装收敛为
:func:`build_progress_payload`；三个原方法保留各自签名，退化成薄委托。

与历史实现逐条对齐的行为（不要"顺手优化"）：

1. 回调为假值（``None`` / 空串等）→ 直接 return，连 payload 都不构造；
2. payload 的构造在 ``try`` 内完成（因此取 state 字段、拼 dict 时抛的异常也会被
   就地吞掉并打 warning，与收敛前一致）；调用方需把拼装包成零参 callable 传进来；
3. ``callback(progress_data)`` 的返回值**无条件 await**：回调是普通函数（返回非协程）
   时 ``await`` 抛 ``TypeError``，同样落进 ``except Exception`` 被吞掉并打 warning，
   与收敛前一致——不要改成 ``if isawaitable(...)`` 的"温和版"，那会悄悄改掉这条路径；
4. 一切异常都不上抛，只按调用点原有的 logger 与原文案打 warning。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional
import logging

_module_logger = logging.getLogger(__name__)

__all__ = ["build_progress_payload", "emit_progress"]

# 收敛前 answer/*（单空格）与 retrieval/*（双空格）的告警文案就有出入，
# 各自原样保留，故做成参数而不是统一成一条。
DEFAULT_FAILURE_WARNING = "⚠️ 发送进度更新失败: {error}"


def build_progress_payload(
    *,
    agent: str,
    stage: str,
    stage_name: str,
    doc_name: str,
    status: str = "processing",
    message: str = "",
    iteration: Optional[int] = None,
    max_iterations: Optional[int] = None,
    tool: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    组装进度 payload（三家字段的并集，键序与收敛前各调用点保持一致）。

    Args:
        agent: 上报来源（"answer" / "retrieval"）。
        stage: 阶段标识。
        stage_name: 阶段中文名。
        doc_name: 文档标识，多文档场景为 "MultiDoc"。
        status: processing / completed / error。
        message: 详细消息。
        iteration: 当前轮次；``None`` 表示该调用点不上报轮次
            （answer 侧不上报，retrieval 侧上报）。
        max_iterations: 最大轮次，与 ``iteration`` 成对出现。
        tool: 本阶段使用的工具（可选，假值不上报，与 retrieval 原实现一致）。
        extra: 追加字段（answer/nodes 的 ``**kwargs`` 从这里进来）。

    Returns:
        可直接交给前端消费的进度字典。
    """
    progress_data: Dict[str, Any] = {
        "agent": agent,
        "stage": stage,
        "stage_name": stage_name,
    }

    if iteration is not None:
        progress_data["iteration"] = iteration
        progress_data["max_iterations"] = max_iterations

    progress_data["status"] = status
    progress_data["message"] = message
    progress_data["doc_name"] = doc_name

    if tool:
        progress_data["tool"] = tool

    if extra:
        progress_data.update(extra)

    return progress_data


async def emit_progress(
    callback: Optional[Callable[..., Any]],
    progress_data: Any,
    *,
    logger: Optional[logging.Logger] = None,
    failure_warning: str = DEFAULT_FAILURE_WARNING,
) -> None:
    """
    发送一条进度（三家 ``_send_progress`` 的共同骨架）。

    Args:
        callback: 进度回调；假值时直接返回（与三家的 ``if not ...: return`` 一致，
            是**假值判断**而不是 ``is None``）。
        progress_data: 已组装好的 payload，或一个零参 callable（callable 形态下
            在 ``try`` 内才被调用，从而与收敛前"payload 构造也在 try 里"的语义一致）。
        logger: 失败时打 warning 用的 logger；省略时用本模块 logger。
        failure_warning: 失败文案模板，``{error}`` 占位异常对象。
    """
    if not callback:
        return

    log = logger if logger is not None else _module_logger

    try:
        payload = progress_data() if callable(progress_data) else progress_data
        await callback(payload)
    except Exception as e:
        log.warning(failure_warning.format(error=e))
