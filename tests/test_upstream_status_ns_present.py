"""`ns_present` 只能由 store 级清单回答——"存在但 0 行"不是"不存在"。

`upstream_status(namespace)` 拿不到行时做了一次 store 级交叉判定。原写法
在判定**之前**就无条件写 `ns_present=False`，交叉视图只是改 note：一个存在
但恰好没有行的 ns 会被报成"清单里没有"，把排查往"没这个 namespace"的方向
带偏。这条是 2026-11-25 修该判别位后的回归钉。
"""
import pytest

from src.memory import upstream


class _ScopedStatusClient:
    """status 语义与上游一致：带 namespace 收窄到该 ns，不带就是 store 全景。"""

    def __init__(self, ns_rows, store_total):
        self.ns_rows = dict(ns_rows)
        self.store_total = store_total

    def status(self, namespace=None, **kw):
        if namespace is None:
            return {"namespaces": dict(self.ns_rows),
                    "total": self.store_total,
                    "empty": self.store_total == 0}
        return {"namespaces": {namespace: self.ns_rows.get(namespace, 0)},
                "total": self.ns_rows.get(namespace, 0),
                "empty": self.ns_rows.get(namespace, 0) == 0}


@pytest.fixture()
def store(monkeypatch):
    def _install(ns_rows, store_total):
        client = _ScopedStatusClient(ns_rows, store_total)
        monkeypatch.setattr(upstream, "_client", client)
        return client
    return _install


async def test_exists_but_empty_namespace_reports_present_true(store):
    store({"AATF": 0, "ai-research": 5}, store_total=5)
    out = await upstream.upstream_status("AATF")
    assert out["available"] is True
    assert out["total"] == 0
    assert out["ns_present"] is True, "存在但 0 行的 ns 被谎报成清单里没有"
    assert "存在" in out["note"] and "0 行" in out["note"]


async def test_genuinely_absent_namespace_reports_present_false(store):
    store({"AATF": 0, "ai-research": 5}, store_total=5)
    out = await upstream.upstream_status("nope")
    assert out["ns_present"] is False
    assert "清单里没有" in out["note"]
