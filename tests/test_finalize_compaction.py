"""finalize 收尾调用的上下文裁剪（2026-11-25 补）。

120k 整轮护栏只在迭代边界看，finalize 恰恰在超预算边缘触发；原样发全量
在大窗口上只是贵，在小窗口 provider 上是必炸的 400——兜底接住后给用户
的只剩"答不上来"。这条测试钉的是：裁剪必到位、配对必须一个不少、
预算内绝不无端动刀。
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.orchestrator.agent import (FINALIZE_CONTEXT_BUDGET,
                                            _compact_messages_for_finalize,
                                            _context_chars)


def _build(n_pairs=40, big=8000):
    msgs = [SystemMessage(content="system prompt"), HumanMessage(content="原始问题")]
    for i in range(n_pairs):
        msgs.append(AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": f"c{i}"}]))
        msgs.append(ToolMessage(content="结" * big, tool_call_id=f"c{i}"))
    msgs.append(AIMessage(content="最后一轮的草稿"))
    return msgs


def test_compact_reaches_budget_and_keeps_tool_pairing():
    msgs = _build()
    assert _context_chars(msgs) > FINALIZE_CONTEXT_BUDGET
    out = _compact_messages_for_finalize(msgs)
    assert _context_chars(out) <= FINALIZE_CONTEXT_BUDGET
    assert len(out) == len(msgs), "裁剪只动内容，不许删消息"
    # 头：系统提示与原始问题原样
    assert isinstance(out[0], SystemMessage) and isinstance(out[1], HumanMessage)
    assert "原始问题" in str(out[1].content)
    # 尾：最后一轮原样
    assert out[-1] is msgs[-1]
    # tool_calls 与 ToolMessage 的 id 配对必须完好——API 校验的下限
    ids_a = {tc["id"] for m in out if getattr(m, "tool_calls", None) for tc in m.tool_calls}
    ids_b = {m.tool_call_id for m in out if isinstance(m, ToolMessage)}
    assert ids_a == ids_b and ids_a, "配对在裁剪中被弄丢了"


def test_under_budget_is_untouched():
    msgs = _build(n_pairs=1, big=10)
    assert _compact_messages_for_finalize(msgs) is msgs, "没超预算就不该动刀"
