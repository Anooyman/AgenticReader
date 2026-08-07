"""
每个 Agent/阶段可单独指定要用的 LLM 模型名（覆盖 provider 的默认模型）。

用法：AgentBase.__init__ 在没有显式传入 model 参数时，会用自己的 name
（如 "IndexingAgent"）到这里查一次；查到就用查到的值，查不到（值为
None/键不存在）就沿用该 provider 的环境变量默认模型（LLM_CONFIG 里的
CHAT_MODEL_NAME / OPENAI_MODEL_NAME 等），行为与改造前完全一致。

调优某一个阶段单独用哪个模型时，只改这个表，不用碰调用代码。
"""
from typing import Dict, Optional

AGENT_MODEL_OVERRIDES: Dict[str, Optional[str]] = {
    "IndexingAgent": None,
    "AnswerAgent": None,
    "RetrievalAgent": None,
    "SearchAgent": None,
    # 以下三项对应 ai-research-pipeline 合并计划里将新增的模块，
    # 提前占位以便实现时直接按 name 查表，不需要再改这份配置的结构。
    "Orchestrator": None,
    "MemorySearch": None,
    "QABrief": None,
}
