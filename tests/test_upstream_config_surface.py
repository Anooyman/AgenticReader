"""`GET /api/v1/memory/upstream` 里的**配置自述**位。

这一格是整套联动里最容易被忽略、却最说明"谁在管配置"的地方：前端页面上那句
"记忆模型/维度/目录由 LLM-Memory 决定"，要么来自上游亲口说的，要么来自 AR
自己抄了一份常量。后者总有一天会和上游说的不一样——所以这里钉三件事：

1. 上游给得出自述，页面就必须拿得到**上游那份原文**（维度、模型、source_type
   等键），键名一个不改；
2. 上游**不可达**时不得出现 `config`，也不能编一个看起来真的存在的答案；
3. 上游可达但这一面缺失（老 checkout / 别的实现）时，只能诚实写
   `config_note`，不许拿 AR 自己的常量补一个"大概是这样"的默认值。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.memory import upstream
from src.ui.backend.api.v1 import memory


def _client():
    app = FastAPI()
    app.include_router(memory.router, prefix="/api/v1/memory")
    return TestClient(app)


@pytest.fixture()
def route_env(monkeypatch):
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("LLM_MEMORY_MCP_ENABLED", raising=False)
    monkeypatch.setattr(upstream, "_client", None)
    return monkeypatch


_UPSTREAM_CAPS = {
    "store_dir": "/Users/edward/.llm-memory/memory",
    "dimensions": 512,
    "embedding_model": "bge-m3",
    "chat_model": "gpt-6-luna",
    "insert_model": "gpt-6-luna",
    "insert_model_chain": ["gpt-6-luna", "gpt-5"],
    "source_types": ["brief", "ai_research", "webapp_chat", "web", "repo", "session"],
    "knowledge_types": ["mid", "long"],
    "mcp_default_tools": ["memory_search", "memory_insert"],
    "version": "0.7.4",
}


class _FullStub:
    """有 status 面也有自述面的 SDK 替身。"""

    def status(self, namespace=None):
        return {"namespaces": {"AATF": 12}, "total": 12, "empty": False, "store_dir": "/stub"}

    def capabilities(self):
        return dict(_UPSTREAM_CAPS)


class _NoCapsStub:
    """老 checkout：SDK 在、status 面在，但**没有** capabilities 这一面。"""

    def status(self, namespace=None):
        return {"namespaces": {"AATF": 12}, "total": 12, "empty": False, "store_dir": "/stub"}


def test_upstream_answers_for_its_own_config(route_env):
    route_env.setattr(upstream, "_client", _FullStub())
    body = _client().get("/api/v1/memory/upstream").json()
    assert body["available"] is True
    cfg = body["config"]
    # 上游那套键**原样**过来：改过名就说明 AR 在解释配置
    assert cfg["dimensions"] == 512
    assert cfg["embedding_model"] == "bge-m3"
    assert cfg["store_dir"] == "/Users/edward/.llm-memory/memory"
    assert "brief" in cfg["source_types"]
    assert "capabilities" not in cfg and "read_only" not in cfg, "折叠位不该混进配置"


def test_unreachable_upstream_invents_no_config(route_env):
    """未配置：200 + available:false 是对的，此时**不该**有任何配置位——
    一个没有来源的 dimensions=1536 比缺这一格危险得多。"""
    body = _client().get("/api/v1/memory/upstream").json()
    assert body["available"] is False
    assert "config" not in body


def test_missing_capabilities_face_says_so_instead_of_guessing(route_env):
    # 这个替身没有 capabilities → _require_method 折叠成 available:false + note
    route_env.setattr(upstream, "_client", _NoCapsStub())
    body = _client().get("/api/v1/memory/upstream").json()
    assert body["available"] is True, "缺的是自述面，不是整个上游"
    assert "config" not in body
    assert body.get("config_note"), "缺面必须留一个字面说明，别静默消失"


def test_config_block_survives_a_failing_capabilities_call_without_500(route_env, monkeypatch):
    """上游这面炸了（不是缺方法而是抛异常）时，这个状态查询还得是 200。
    状态页拿 500 谎报"接口坏了"从来不是我们要的形状。"""

    class _ExplodingCaps(_FullStub):
        def capabilities(self):
            raise RuntimeError("config.json unreadable")

    route_env.setattr(upstream, "_client", _ExplodingCaps())
    r = _client().get("/api/v1/memory/upstream")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert "config" not in body and body.get("config_note")


def test_gateway_does_not_rewrite_the_upstream_config(route_env, monkeypatch):
    """中间层一个字都不该改——这是转发的定义。直接拿 gateway 的结果和上游
    的字典比，比"形状看着差不多"更有约束力。"""
    import asyncio

    from src.memory import gateway

    monkeypatch.setattr(upstream, "_client", _FullStub())
    got = asyncio.run(gateway.upstream_capabilities())
    assert {k: v for k, v in got.items() if k not in ("available", "read_only")} == _UPSTREAM_CAPS


def test_the_store_root_note_prefers_the_authitys_own_answer(monkeypatch):
    """能问到就别自己算——这句诊断的**出处**比它好不好看更要紧。"""
    class _SelfReporting:
        def capabilities(self):
            return {"store_dir": "/somewhere/upstream/memory", "store_source": "default"}

    monkeypatch.setattr(upstream, "_client", _SelfReporting())
    monkeypatch.setattr(upstream, "_repo_src", lambda: "/tmp/llm-memory/src")
    note = upstream._store_root_note()
    assert "上游自报" in note and "source=default" in note
    assert "/somewhere/upstream/memory" in note


def test_without_a_client_it_says_so_instead_of_passing_off_a_guess(monkeypatch):
    """没有 client 时只能按 paths 现算——那就把这条路数写进句子里，
    否则读者会以为这是上游亲口说的。"""
    monkeypatch.setattr(upstream, "_client", None)
    monkeypatch.setattr(upstream, "_repo_src", lambda: "/tmp/llm-memory/src")
    note = upstream._store_root_note()
    assert "现算" in note or "算不出" in note, f"该承认出处的地方别含糊：{note}"
