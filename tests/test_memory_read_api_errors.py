"""`/data` 的读端点：空是答案，读不出来是事故。

这两个状态原来在这里是同一种表现——都是 200，都是一个空列表——区别只在
日志里（甚至可能只在日志里）。对一个显示"共 0 条记忆"的页面来说，那是最
省事也最贵的一种混淆：一次存储故障会被用户读成"这个库本来就什么都沒有"。

现在分开：

* 库里真的没有行 → **200**，形状照旧（`total: 0` / 空 namespaces）。状态查询
  本来就该如实回答"没有"，拿 4xx/5xx 谎报接口坏了是这个文件反对的另一种错。
* 读取本身失败（上游挂了、库打不开、`MEMORY_STORE_MODE=upstream` 下路由
  抛错）→ **502**，理由进 body。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.memory.gateway as gateway
from src.ui.backend.api.v1 import memory


def _client():
    app = FastAPI()
    app.include_router(memory.router, prefix="/api/v1/memory")
    return TestClient(app)


# ------------------------------------------------------------------ 故障不是空
def test_overview_failure_says_why_instead_of_showing_zero(monkeypatch):
    def boom(namespace="*"):
        raise RuntimeError("本地旧库打不开：data/memory_db 缺表")

    # overview 的本地计数走 browse_all_rows_local（两账并列的本地那本账），
    # 路由版 browse_all_rows 只服务命名空间明细视图——缝不一样，别打错。
    monkeypatch.setattr(gateway, "browse_all_rows_local", boom)
    r = _client().get("/api/v1/memory/overview")
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "缺表" in detail, f"要把原因交给调用方：{detail!r}"


def test_namespace_view_failure_also_carries_the_reason(monkeypatch):
    def explode(*_a, **_kw):
        raise OSError("LanceDB 打不开那个目录")

    monkeypatch.setattr(gateway, "browse_all_rows", explode)
    r = _client().get("/api/v1/memory/namespace/AATF")
    assert r.status_code == 502
    assert "LanceDB" in r.json()["detail"]


# ------------------------------------------------------------------ 空就是空
def test_a_genuinely_empty_library_still_answers_200(monkeypatch):
    """空列表在这里是对的——不许为了"显得出错"而升级成 5xx。"""
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    monkeypatch.setattr(gateway, "browse_all_rows_local", lambda namespace="*": [])
    r = _client().get("/api/v1/memory/overview")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_the_empty_namespace_view_keeps_its_shape(monkeypatch):
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    monkeypatch.setattr(gateway, "browse_all_rows", lambda namespace="*": [])
    r = _client().get("/api/v1/memory/namespace/AATF")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0 and body["groups"] == [] and body["namespace"] == "AATF"


def test_a_real_overview_keeps_the_same_keys(monkeypatch):
    rows = [{"id": "r1", "namespace": "AATF", "source_type": "brief", "importance": 0.4,
             "created_at": "2026-11-22T00:00:00+00:00"},
            {"id": "r2", "namespace": "webapp-chat", "source_type": "webapp_chat",
             "importance": 0.6, "created_at": "2026-11-21T00:00:00+00:00"}]
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    monkeypatch.setattr(gateway, "browse_all_rows_local", lambda namespace="*": rows)
    body = _client().get("/api/v1/memory/overview").json()
    assert body["total"] == 2
    assert {n["namespace"] for n in body["namespaces"]} == {"AATF", "webapp-chat"}
    assert all("source_types" in n for n in body["namespaces"])
