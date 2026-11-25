"""/data 页上"删除"这件事失败时，界面拿到的到底是什么。

删除和读不一样：读失败可以 200 + `available:false`（状态页不该谎报接口坏了），
但**操作失败必须是失败**，而且要把原因带回来。原来这三个 DELETE 路由直接把
service 的异常往上传，FastAPI 给的是一句 `Internal Server Error`——状态码是
对的，内容却什么都没写，用户只知道"没删掉"，不知道为什么，也就不知道该不该
再点一次。这里补的是内容：

* `ValueError`（空 namespace / `*` 这类**调用方**给错的 scope）→ **400**，
  理由是护栏原话；
* 上游或存储真的出问题了 → **502**，理由原样进 body，日志里也留一条；
* 成功 → 还是那个 `{ok, deleted}` 形状，UI 不用改。

两种失败都不许留下"成功了一半"的返回体。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ui.backend.api.v1 import memory
from src.ui.backend.services import memory_browse


def _client():
    app = FastAPI()
    app.include_router(memory.router, prefix="/api/v1/memory")
    return TestClient(app)


# ------------------------------------------------------------------ 调用方的错
@pytest.mark.parametrize("namespace", ["*", "%2A"])
def test_a_wildcard_namespace_is_the_callers_error_not_the_servers(_client_isolated, namespace):
    c = _client()
    r = c.delete(f"/api/v1/memory/namespace/{namespace}")
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "namespace" in detail and "refusing to delete" in detail, \
        "护栏的话要原样传给调用方，别缩成一句通用错误"


def test_wildcard_source_delete_also_blames_the_caller(_client_isolated):
    c = _client()
    r = c.delete("/api/v1/memory/namespace/%2A/source/doc-1")
    assert r.status_code == 400


# ------------------------------------------------------------------ 我们/上游的错
def test_an_upstream_failure_comes_back_with_its_reason(monkeypatch):
    def boom(namespace, source_id):
        raise RuntimeError("上游 delete_where 失败：上游没有这个库")

    monkeypatch.setattr(memory_browse, "delete_source", boom)
    r = _client().delete("/api/v1/memory/namespace/webapp-chat/source/s-1")
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "delete_where" in detail and "没有这个库" in detail, \
        f"失败原因必须原样可见，而不是只剩状态码：{detail!r}"
    assert "ok" not in r.json(), "失败的时候不许还带一个 ok 字段"


def test_a_service_exception_never_returns_ok_true(monkeypatch):
    def boom(memory_id):
        raise TimeoutError("上游没在期限内回话")

    monkeypatch.setattr(memory_browse, "delete_memory", boom)
    r = _client().delete("/api/v1/memory/item/abc")
    assert r.status_code == 502
    assert "TimeoutError" in r.json()["detail"]


# ------------------------------------------------------------------ 成功形状
def test_a_successful_delete_keeps_the_old_body(monkeypatch):
    async def ok_source(namespace, source_id):
        return {"ok": True, "deleted": 3, "source_id": source_id}

    monkeypatch.setattr(memory_browse, "delete_source", ok_source)
    r = _client().delete("/api/v1/memory/namespace/webapp-chat/source/s-1")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "deleted": 3, "source_id": "s-1"}


def test_namespace_clear_reports_how_many_rows_it_took(monkeypatch):
    async def ok_namespace(namespace):
        return {"ok": True, "deleted": 0, "namespace": namespace}

    monkeypatch.setattr(memory_browse, "delete_namespace", ok_namespace)
    r = _client().delete("/api/v1/memory/namespace/ai-research")
    assert r.status_code == 200
    assert r.json()["deleted"] == 0, "0 条不是失败，别把它翻译成错误"


# ------------------------------------------------------------------ 真护栏走真路由
@pytest.fixture()
def _client_isolated(monkeypatch):
    """护栏那两条不打桩——它本来就该在 service 之前挡住，打桩了反而测不到。"""
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    import src.memory.upstream as upstream
    monkeypatch.setattr(upstream, "_client", None)

    class _Never:
        def all_rows(self, *_a, **_kw):
            raise AssertionError("护栏应该在此刻之前就把它挡掉")

        rows_for_source = delete = add = all_rows
    import src.memory.gateway as gateway
    monkeypatch.setattr(gateway, "_store", lambda provider=None: _Never())
    return monkeypatch
