"""Orchestrator——research chat 的多 session 对话编排层，ReAct 循环驱动
两个子 agent（search_memory / deep_dive_document）。改自
ai-research-pipeline，合并进 AgenticReader 后子 agent 均为同进程直接调用。
"""
from src.agents.orchestrator.agent import ask

__all__ = ["ask"]
