"""RetrievalAgent 的 format 节点兜底回归——卫生扫描时判出的那条"漏接线"：

format 节点在 `formatted_data` 为空时的日志原话是"使用中间总结作为最终答案"，
但下面那行赋值被注释掉了——于是 state["final_summary"] 从头到尾没被写过，
RetrievalAgent 返回体（agent.py:229 的 .get("final_summary", "")）和
AnswerAgent 的检索上下文（tools.py:298）双双拿到空串。也就是说检索真的
一无所获时，用户看到的不是"没检索到内容"，而是一个空答案。异常那条路同理。

顺带钉住三处卫生改动没有改变行为：
  * think 节点不再另算 executed_tools（工具名本来就在 history_json 里）；
  * evaluate 节点去掉了 attempted_strategies 占位；
  * summary 失败路径写下的 intermediate_summary 现在有了唯一消费点。

全部是纯逻辑，不调 LLM、不读真实索引。
"""
import asyncio

from src.agents.retrieval.nodes import RetrievalNodes


class _StubLLM:
    """只填 format 节点用到的接口：正常出题返回答案，boom=True 就炸。"""

    def __init__(self, boom: bool = False, reply: str = "答案正文"):
        self.boom = boom
        self.reply = reply
        self.calls = []

    async def async_call_llm_chain(self, role=None, input_prompt=None,
                                   session_id=None, system_format_dict=None, **kw):
        self.calls.append(input_prompt)
        if self.boom:
            raise RuntimeError("LLM 挂了")
        return self.reply


class _StubAgent:
    def __init__(self, llm: _StubLLM):
        self.current_doc = "doc.pdf"
        self.progress_callback = None
        self.llm = llm
        self.persistent_state = {}


def _nodes(llm: _StubLLM) -> RetrievalNodes:
    return RetrievalNodes(_StubAgent(llm))


def _base_state(**over):
    state = {
        "query": "这个模型怎么训的",
        "rewritten_query": "这个模型怎么训的",
        "doc_name": "doc.pdf",
        "conversation_turn": 0,
        "current_iteration": 0,
        "max_iterations": 3,
        "is_complete": False,
        "thoughts": [],
        "actions": [],
        "observations": [],
        "retrieved_content": [],
        "formatted_data": [],
    }
    state.update(over)
    return state


# ------------------------------------------------ format 的空数据兜底
def test_format_uses_intermediate_summary_when_no_formatted_data():
    """失败路径写下的那句"未检索到相关内容"终于被接到最终答案上。"""
    llm = _StubLLM()
    state = _base_state(formatted_data=[], intermediate_summary="未检索到相关内容")
    out = asyncio.run(_nodes(llm).format(state))
    assert out["final_summary"] == "未检索到相关内容"
    # 没数据就不该白跑一次生成答案的 LLM 调用
    assert llm.calls == []


def test_format_falls_back_to_explicit_hint_when_summary_also_empty():
    llm = _StubLLM()
    state = _base_state(formatted_data=[], intermediate_summary="")
    out = asyncio.run(_nodes(llm).format(state))
    summary = out["final_summary"]
    assert summary.strip(), "空 formatted_data + 空中间总结时也必须给出文字"
    assert "检索" in summary
    assert llm.calls == []


def test_format_error_path_still_leaves_readable_final_summary():
    """异常被就地接住后，调用方拿到的 final_summary 不能是空串。"""
    llm = _StubLLM(boom=True)
    state = _base_state(
        formatted_data=[{"index": 1, "type": "content", "title": "第 1 章",
                         "pages": [1], "content": "一些正文", "raw_data": {}}],
    )
    out = asyncio.run(_nodes(llm).format(state))
    assert out["final_summary"].strip()
    assert "出错" in out["final_summary"]


def test_format_normal_path_unaffected_by_the_fallbacks():
    """反向确认：有内容时仍然是 LLM 生成的答案，兜底不该插嘴。"""
    llm = _StubLLM(reply="  真实答案 ")
    state = _base_state(
        formatted_data=[{"index": 1, "type": "content", "title": "第 1 章",
                         "pages": [1], "content": "一些正文", "raw_data": {}}],
    )
    out = asyncio.run(_nodes(llm).format(state))
    assert out["final_summary"].strip() == "真实答案"
    assert len(llm.calls) == 1


# ------------------------------------------------ 卫生改动的行为不变
def test_think_survives_without_executed_tools_local():
    """executed_tools 那个局部量删掉后，think 仍然正常走通并把历史交给 LLM。"""
    llm = _StubLLM(reply='{"thought": "继续", "action": "get_section_content", '
                        '"action_input": {}}')
    state = _base_state(
        actions=[{"tool": "get_document_structure", "params": {}}],
        observations=["获取 5 项数据"],
        retrieved_content=[{"type": "structured_info", "tool": "get_document_structure",
                            "data": ["1 引言"], "metadata": {}}],
    )
    out = asyncio.run(_nodes(llm).think(state))
    assert isinstance(out, dict)
    assert llm.calls, "think 该发起一次工具选择的 LLM 调用"
    # 历史 JSON 里带 tool 字段——这正是当初觉得 executed_tools 多余的依据
    assert "get_document_structure" in llm.calls[0]


def test_evaluate_survives_without_attempted_strategies_placeholder():
    """evaluate 里的 attempted_strategies 只是旧启发式的空壳，删掉不影响它
    照常把 LLM 的判定写回 is_complete / reason。

    注意喂一份非空的 formatted_data：evaluate 在"无格式化数据"时有条短路
    分支（直接判不完整、根本不问 LLM），那不是这次改动的部分。
    """
    llm = _StubLLM(reply='{"is_complete": false, "reason": "还缺章节 3"}')
    state = _base_state(
        formatted_data=[{"index": 1, "type": "content", "title": "第 1 章",
                         "pages": [1], "content": "一些正文", "raw_data": {}}],
        actions=[{"tool": "get_section_content", "params": {}}],
        observations=["新增 2 个结果"],
    )
    out = asyncio.run(_nodes(llm).evaluate(state))
    assert out["reason"] == "还缺章节 3"
    assert out["is_complete"] is False


def test_summary_failure_text_lands_in_intermediate_summary():
    """summary 的"无检索内容"路仍然把话说给 intermediate_summary——
    它就是 format 兜底要读的那句，别断。"""
    llm = _StubLLM()
    state = _base_state(retrieved_content=[], last_result=[], current_tool="get_section_content")
    out = asyncio.run(_nodes(llm).summary(state))
    assert out["intermediate_summary"] == "未检索到相关内容"
