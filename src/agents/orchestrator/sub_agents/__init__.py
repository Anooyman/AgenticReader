"""Orchestrator 可调用的子 agent 注册表。"""
from src.agents.orchestrator.sub_agents.base import ProgressCallback, SubAgent
from src.agents.orchestrator.sub_agents.deep_dive import DeepDiveAgent
from src.agents.orchestrator.sub_agents.memory_search import MemorySearchAgent
from src.agents.orchestrator.sub_agents.web_search import WebSearchAgent

# 注意顺序：注册表是全量工具池，"这次会话里哪些可以广告给模型"由
# orchestrator.agent 按 enabled_tools 过滤（见 _tool_names_allowed）——
# search_web 属于"要开关才开"的那类，另两个恒开。
SUB_AGENTS = {
    MemorySearchAgent.name: MemorySearchAgent(),
    DeepDiveAgent.name: DeepDiveAgent(),
    WebSearchAgent.name: WebSearchAgent(),
}

# 不受会话工具开关影响的恒开工具。
ALWAYS_ON_TOOLS = frozenset({MemorySearchAgent.name, DeepDiveAgent.name})
