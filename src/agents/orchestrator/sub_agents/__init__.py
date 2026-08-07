"""Orchestrator 可调用的子 agent 注册表。"""
from src.agents.orchestrator.sub_agents.base import ProgressCallback, SubAgent
from src.agents.orchestrator.sub_agents.deep_dive import DeepDiveAgent
from src.agents.orchestrator.sub_agents.memory_search import MemorySearchAgent

SUB_AGENTS = {
    MemorySearchAgent.name: MemorySearchAgent(),
    DeepDiveAgent.name: DeepDiveAgent(),
}
