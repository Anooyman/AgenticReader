"""Orchestrator——research chat 的多 session 对话编排层，ReAct 循环驱动。
子 agent 有三个：search_memory（→ src.memory）、deep_dive_document
（→ AnswerAgent）、search_web（→ SearchAgent，仅在会话开启网络搜索时才
进工具集）。改自 ai-research-pipeline，合并进 AgenticReader 后子 agent
均为同进程直接调用。
"""
from src.agents.orchestrator.agent import ask

__all__ = ["ask"]
