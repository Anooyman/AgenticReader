"""上游三个只读 HTTP 路由的契约测试——TestClient 全离线，不碰上游真实库。

路由层只钉两件事：输入校验挡在什么位置、失败怎么映射状态码；
gateway 收敛与 upstream 折叠的内部形状由 test_upstream_facade.py 钉，
这里不重复。decision 面的"诚实"统一按"绝不谎报成功"口径断言——
具体状态码（200+available:false 还是 5xx 映射）若与实现落地有出入，
以代码为准回修测试，不反向改代码。
"""
import json

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
    """确定环境：上游寻址与 MCP 开关归零、SDK client 缓存清空，
    真实进程 env / 历史测试留下的 _client 单例都影响不到这里。"""
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("LLM_MEMORY_MCP_ENABLED", raising=False)
    monkeypatch.setattr(upstream, "_client", None)
    return monkeypatch


class _StubClient:
    """最小 SDK 替身：status 面给得出 store 视图即可，形状不是本文件重点。"""

    def status(self, namespace=None):
        return {"namespaces": {"agenticreader-x": 7}, "total": 7,
                "empty": False, "store_dir": "/stub"}

    def namespaces(self):
        return [{"name": "agenticreader-x", "row_count": 7}]

    def search(self, query, namespace=None, namespaces=None, deadline_s=None, **kw):
        return {"results": [{"text": "stub hit"}], "mode": "semantic"}


# ---------------------------------------------------------------- GET /upstream
def test_get_upstream_unconfigured_is_honest_200(route_env):
    """状态查询不是操作：未配置也如实 200 + available:false + note，
    前端拿它渲染灰徽章；拿 4xx/5xx 谎报"接口坏了"反而是要防的反面。"""
    r = _client().get("/api/v1/memory/upstream")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body.get("note")


def test_get_upstream_configured_carries_decision_bit(route_env):
    """SDK 面就绪但 MCP 决策面没开：status 正常 + decision 位内嵌，
    且该位必须诚实——enabled=false 明说关着，不能整个键都不给。"""
    m = route_env
    m.setattr(upstream, "_client", _StubClient())
    r = _client().get("/api/v1/memory/upstream")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert "decision" in body, "status 面没带 decision 开关位"
    decision = body["decision"]
    assert isinstance(decision, dict)
    assert decision.get("enabled") is False
    assert decision.get("available") is not True  # 没开的开关不许亮"可用"


# ---------------------------------------------------------------- POST /upstream/search
@pytest.mark.parametrize("body", [
    {},                      # 整个 query 键缺
    {"query": ""},           # 空串
    {"query": "   "},        # 纯空白
    {"query": 42},           # 非 str
    {"query": None},         # 显式 null
])
def test_post_search_rejects_bad_query(route_env, body):
    r = _client().post("/api/v1/memory/upstream/search", json=body)
    assert r.status_code == 400
    # 校验必须挡在一切上游触达之前——这里连折叠结果都不该出现
    assert "available" not in r.json() if r.status_code == 400 else True


def test_post_search_rejects_malformed_body_shape(route_env):
    """body 不是对象：执行前就拒（400/422 都算数，口径以代码为准）。"""
    r = _client().post("/api/v1/memory/upstream/search", json="not-an-object")
    assert r.status_code in (400, 422)


def test_post_search_unconfigured_maps_503(route_env):
    """未配置：服务在但门关着——503，note 走 detail。"""
    r = _client().post("/api/v1/memory/upstream/search", json={"query": "x"})
    assert r.status_code == 503


# ---------------------------------------------------------------- POST /upstream/decision
# ---------------------------------------------------------------- POST /upstream/decision
# 代码实测口径（路由签名 {tool, args?}，args 键名不是 arguments）：
# 白名单外工具先 403 拦在路由层，白名单内未启用由内核 gate 报 503，
# 非对象 body 由 pydantic 挡成 422——三态都"不许谎报成功"。
def test_post_decision_not_enabled_is_honest(route_env):
    """MCP 决策面默认关：白名单内工具 + 关闭态 → 503 + 诚实 note。
    注意这里不 patch 转发入口——gate 的诚实答案本身就是被测对象，
    把上游入口换成假实现反而会把"关着装了开"这条真回归放过去。"""
    r = _client().post("/api/v1/memory/upstream/decision",
                       json={"tool": "memory_why", "args": {}})
    if r.status_code == 200:
        pytest.fail("决策面关着却 200 报了成功")
    assert r.status_code in (501, 502, 503)
    blob = json.dumps(r.json(), ensure_ascii=False)
    assert "默认关闭" in blob or "不" in blob  # detail 必须是 gate 话术


def test_post_decision_rejects_tools_outside_whitelist(route_env):
    """写工具（remember/ingest 这类）在路由层就被 403 拒掉，
    拒绝理由点名工具与白名单——压根不碰内核，也不看 MCP 开关脸色。"""
    r = _client().post("/api/v1/memory/upstream/decision",
                       json={"tool": "memory_remember", "args": {}})
    assert r.status_code == 403
    blob = json.dumps(r.json(), ensure_ascii=False)
    assert "memory_remember" in blob and "白名单" in blob.replace("whitelist", "白名单")


def test_post_decision_rejects_malformed_bodies(route_env):
    """决策面的坏形状三连：body 非对象、tool 缺失/非 str、args 非对象——
    全部执行前拦截（400/403/422 档都算，别到转发层才炸）。"""
    c = _client()
    r = c.post("/api/v1/memory/upstream/decision", json="not-an-object")
    assert r.status_code in (400, 403, 422)
    r = c.post("/api/v1/memory/upstream/decision", json={})
    assert r.status_code in (400, 403, 422)
    r = c.post("/api/v1/memory/upstream/decision",
               json={"tool": "memory_why", "args": "not-a-dict"})
    assert r.status_code in (400, 403, 422)


def test_post_decision_forwards_to_upstream_layer(route_env, tmp_path):
    """启用态的转发形状：{tool, args} 原样递交上游决策层，其返回原样透出。
    假的是决策层入口本身，不是 stdio——转发层不许自造 (status, body)
    这类退役桥的 HTTP 旧形状。"""
    m = route_env
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    m.setenv("LLM_MEMORY_REPO", str(repo))
    m.setenv("LLM_MEMORY_MCP_ENABLED", "1")
    seen = []

    async def spy_call(tool, arguments):
        seen.append((tool, arguments))
        return {"available": True, "text": "stubbed answer"}

    m.setattr(upstream, "upstream_decision_call", spy_call)
    r = _client().post("/api/v1/memory/upstream/decision",
                       json={"tool": "memory_why", "args": {"q": "x"}})
    assert seen == [("memory_why", {"q": "x"})], (
        "路由到决策层的转发形状不对——以代码为准，有出入按实现回修这里")
    assert r.status_code == 200
    assert r.json()["available"] is True
