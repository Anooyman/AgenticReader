"""src/memory/gateway.py 边界语义测试——本轮收敛审查后钉死的三处决策：

  * load_brief_date 的 driver 显式白名单 {bridge, local}：非法值 warning 后
    按 bridge 跑（避免误设 env 整条 brief 加载"莫名全挂"），local 是有意
    raise 的预留位，缺省恒 bridge；
  * delete_source / delete_namespace：缺 id 的行跳过并 warning，deleted 只
    计真删，不把幻影行算进返回值给 UI；
  * ingest 与 search 的 provider 归一对称：显式值也过 resolve_provider，
    读写两侧 provider 字符串恒等价。

外加 MemoryScopeRequest 对"缺键 body"的容忍（pydantic v2 下无默认值的
Optional 键仍必填，缺省必须写成显式 None 才不撞 422）。全部用假对象，
不碰 LanceDB / 网络 / 真实会话文件。
"""
import pytest

from src.memory import gateway


# ---------------------------------------------------------------- driver 分派
def test_driver_unset_is_bridge(monkeypatch):
    monkeypatch.delenv("MEMORY_BRIEF_DRIVER", raising=False)
    import src.ui.backend.services.brief_memory as bm
    seen = {}

    async def fake_load_date(date):
        seen["date"] = date
        return {"loaded": True, "skipped": False, "errors": []}

    monkeypatch.setattr(bm, "load_date", fake_load_date)
    out = _run(gateway.load_brief_date("2026-11-13"))
    assert out == {"loaded": True, "skipped": False, "errors": []}
    assert seen["date"] == "2026-11-13"


def test_driver_illegal_value_warns_and_falls_back_to_bridge(monkeypatch, caplog):
    monkeypatch.setenv("MEMORY_BRIEF_DRIVER", "brdge  ")  # 笔误也要接住
    import src.ui.backend.services.brief_memory as bm
    called = []

    async def fake_load_date(date):
        called.append(date)
        return {"loaded": False, "skipped": True, "errors": []}

    monkeypatch.setattr(bm, "load_date", fake_load_date)
    with caplog.at_level("WARNING"):
        out = _run(gateway.load_brief_date("2026-11-13"))
    assert called == ["2026-11-13"]           # 照常走 bridge
    assert out["skipped"] is True
    assert "不在白名单" in caplog.text


def test_driver_local_is_reserved_raise(monkeypatch):
    monkeypatch.setenv("MEMORY_BRIEF_DRIVER", "local")
    with pytest.raises(NotImplementedError):
        _run(gateway.load_brief_date("2026-11-13"))


def _run(coro):
    """同步跑一个协程（避免每个用例重复 import asyncio；本文件无 fixture 依赖）。"""
    import asyncio
    return asyncio.run(coro)


# ---------------------------------------------------------------- 删除计数
class _FakeStore:
    def __init__(self, rows, fail_ids=()):
        self._rows = rows
        self._fail = set(fail_ids)
        self.deleted = []

    def rows_for_source(self, namespace, source_id):
        return list(self._rows)

    def all_rows(self, namespace):
        return list(self._rows)

    def delete(self, row_id):
        if row_id in self._fail:
            raise RuntimeError("db hiccup")
        self.deleted.append(row_id)


def test_delete_source_skips_idless_and_failing_rows(monkeypatch):
    rows = [{"id": "a"}, {"text": "phantom"}, {"id": "boom"}, {"id": "b"}]
    store = _FakeStore(rows, fail_ids={"boom"})
    monkeypatch.setattr(gateway, "_store", lambda provider=None: store)
    n = gateway.delete_source("ai-research", "doc-x")
    assert n == 2                                  # 只计真删：a + b
    assert store.deleted == ["a", "b"]             # 幻影行从未被 delete('')


def test_delete_namespace_skips_idless_rows(monkeypatch):
    rows = [{}, {"id": "c"}, {"id": "d"}]
    store = _FakeStore(rows)
    monkeypatch.setattr(gateway, "_store", lambda provider=None: store)
    assert gateway.delete_namespace("webapp-chat") == 2
    assert store.deleted == ["c", "d"]


# ---------------------------------------------------------------- scope 模型
def test_memory_scope_request_tolerates_missing_key():
    """恢复默认最顺手的写法（整个键都缺）必须可用，不能撞 422。"""
    from src.ui.backend.api.v1.sessions import MemoryScopeRequest
    assert MemoryScopeRequest().namespaces is None
    assert MemoryScopeRequest(namespaces=None).namespaces is None
    assert MemoryScopeRequest(namespaces=["ai-research"]).namespaces == ["ai-research"]


# ---------------------------------------------------------------- provider 归一
def test_ingest_normalizes_explicit_provider_like_search(monkeypatch):
    captured = {}

    async def fake_ingest(path, source_type=None, namespace=None,
                          provider=None, source_id=None):
        captured["provider"] = provider
        return {}

    # gateway 命名空间里 resolve_provider 是可 patch 的接缝；写侧必须
    # 像 search() 一样把显式值（含大小写/空白）过一遍归一，与读侧等价。
    monkeypatch.setattr(gateway, "resolve_provider", lambda p: f"resolved[{p}]")
    monkeypatch.setattr(gateway, "_ingest_source", fake_ingest)
    _run(gateway.ingest("/tmp/x", "pdf", "ai-research", provider=" Azure "))
    assert captured["provider"] == "resolved[ Azure ]"
