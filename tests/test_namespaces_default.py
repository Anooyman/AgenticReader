"""D-B 检索作用域三态语义的回归测试（blueprint Phase 0 验收项）。

纯本地运行：不联网、不调 LLM——gateway.search 被 monkeypatch 成记录
入参的假实现，agentic_search 的真实工具循环不触发。
"""
import pytest

from src.memory import gateway


def test_resolve_none_is_whitelist():
    for empty in (None, "", [], [""]):
        got = gateway.resolve_search_namespaces(empty)
        assert got == [gateway.NAMESPACE_AI_RESEARCH, gateway.NAMESPACE_WEBAPP_CHAT], empty
    assert gateway.resolve_search_namespaces(None) == gateway.DEFAULT_SEARCH_NAMESPACES


def test_resolve_wildcard_is_star():
    assert gateway.resolve_search_namespaces("*") == "*"
    assert gateway.resolve_search_namespaces(["*"]) == "*"
    # 含 "*" 的列表也归并为全部（与 vector_store 层 "*" 不生成过滤的
    # 行为一致，天花板在 gateway 层，不反转"省略=全部"）
    assert gateway.resolve_search_namespaces(["ai-research", "*"]) == "*"


def test_resolve_explicit_list_subset_dedup():
    assert gateway.resolve_search_namespaces(["ai-research", "ai-research", ""]) == ["ai-research"]
    assert gateway.resolve_search_namespaces([" webapp-chat ", "webapp-chat"]) == ["webapp-chat"]
    assert gateway.resolve_search_namespaces(["AATF"]) == ["AATF"]


@pytest.mark.asyncio
async def test_subagent_default_is_whitelist(monkeypatch):
    """MemorySearchAgent 缺省不传 namespaces 时，经过 gateway 的
    resolve_search_namespaces 后落到底层 agentic_search 的值恰是自库
    白名单（而非 None/"*"）——blueprint 0.4 缺省常量的验收点。
    （patch 点在 gateway 之下：sub-agent→gateway 传的是原始值，
    三态解析发生在 gateway.search 内部。）"""
    captured = {}

    async def fake_agentic_search(query, namespace=None, provider=None, max_iterations=None):
        captured["namespace"] = namespace
        return {"answer": "ok", "results": [], "iterations": 1, "tool_calls_made": 0}

    monkeypatch.setattr(gateway, "_agentic_search", fake_agentic_search)
    from src.agents.orchestrator.sub_agents.memory_search import MemorySearchAgent

    out = await MemorySearchAgent().invoke(query="q")
    assert captured["namespace"] == gateway.DEFAULT_SEARCH_NAMESPACES
    assert "answer" in out


@pytest.mark.asyncio
async def test_subagent_explicit_wildcard_passthrough(monkeypatch):
    """显式 namespaces="*" 一路透传成底层 namespace="*"（D-B (b) 态），
    不被换成白名单。"""
    captured = {}

    async def fake_agentic_search(query, namespace=None, provider=None, max_iterations=None):
        captured["namespace"] = namespace
        return {"answer": "", "results": []}

    monkeypatch.setattr(gateway, "_agentic_search", fake_agentic_search)
    from src.agents.orchestrator.sub_agents.memory_search import MemorySearchAgent

    await MemorySearchAgent().invoke(query="q", namespaces="*")
    assert captured["namespace"] == "*"
