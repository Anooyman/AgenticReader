"""ANSWER_TOOLS 与 plan 分支的机器守护。

"注册表 + 分发 + plan 构造"三处一致的纪律以前只靠人肉：新工具加进
ANSWER_TOOLS 而 plan 的 if/elif 忘了加分支时，它会被**静默跳过**——
工具明明可选，plan 就是不会调用它，没有任何一行日志承认过跳过。
这条测试把这个缺口从"约定"变成"会红"。
"""
import inspect

from src.agents.answer import nodes
from src.agents.answer.tools_config import ANSWER_TOOLS


def test_plan_builder_mentions_every_registered_tool():
    builder = getattr(nodes.AnswerNodes, "_build_tool_calls_from_user_selection")
    source = inspect.getsource(builder)
    for tool_name in ANSWER_TOOLS:
        assert tool_name in source, (
            f"{tool_name} 在 ANSWER_TOOLS 里注册了，但 plan 的分支里没有它——"
            "这个工具会被静默跳过。需要在 _build_tool_calls_from_user_selection "
            "加构造分支，并同步前端可选工具列表。")
