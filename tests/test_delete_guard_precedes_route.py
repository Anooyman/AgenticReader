"""`delete_*` 的护栏必须在**路由之前**，两条路说法要一模一样。

这段代码原来把 `_guard_scoped_namespace` 放在"走上游"那条分支里面，于是
同一个请求会因为路由不同得到两种结果：接上游时报错拒绝，没接上游时**一声不响
地去扫描本地库**。函数自己的注释写的是"空串或 `*` 直接被拒"，没说"只有接上
上游才拒"——注释和实现不一致的时候，读注释的人反而最危险。

这一组用例把顺序钉死：

* 未接上游（本地路）：无 scope 的 `delete_source` / `delete_namespace` 必须是
  `ValueError`，而且**一次都不该去碰本地库**——护栏的作用就是别让它有机会动手；
* 接上游：同样的三种入参同样被拒（防止哪天又把护栏挪回分支里）；
* 有 scope 的正常入参不受影响，两条路都还是老语义。
"""
import pytest

import src.memory.gateway as gateway
import src.memory.upstream as upstream


class _Store:
    def __init__(self):
        self.touched = []

    def all_rows(self, namespace):
        self.touched.append(("all_rows", namespace))
        return [{"id": "l1", "source_id": "x", "namespace": namespace}]

    def rows_for_source(self, namespace, source_id):
        self.touched.append(("rows_for_source", namespace, source_id))
        return [{"id": "l1"}]

    def delete(self, row_id):
        self.touched.append(("delete", row_id))
        return 1


@pytest.fixture()
def local_only(monkeypatch):
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    monkeypatch.setattr(upstream, "_client", None)
    store = _Store()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: store)
    return store


@pytest.fixture()
def upstream_on(monkeypatch, tmp_path):
    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    store = _Store()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: store)

    class _C:
        def __init__(self):
            self.calls = []

        def delete_where(self, namespace=None, namespaces=None, source_type=None,
                         source_id=None, tier=None, cwd=None, dry_run=False):
            self.calls.append((namespace, source_id))
            return {"status": "ok", "deleted": 1}

        def delete(self, ids=None, namespace=None, namespaces=None, cwd=None):
            self.calls.append(("delete", ids, namespace))
            return {"status": "ok", "deleted": 1}

    client = _C()
    monkeypatch.setattr(upstream, "_client", client)
    return client, store


# ------------------------------------------------------------------ 未接上游
@pytest.mark.parametrize("args", [("", "x"), ("*", "x")])
def test_unscoped_delete_source_is_refused_locally(local_only, args):
    ns, sid = args
    with pytest.raises(ValueError):
        gateway.delete_source(ns, sid)
    assert local_only.touched == [], "护栏后面还去扫了本地库，等于没挡"


@pytest.mark.parametrize("ns", ["", "*"])
def test_unscoped_delete_namespace_is_refused_locally(local_only, ns):
    with pytest.raises(ValueError):
        gateway.delete_namespace(ns)
    assert local_only.touched == []


def test_a_real_namespace_still_works_locally(local_only):
    assert gateway.delete_source("webapp-chat", "x") == 1
    assert ("rows_for_source", "webapp-chat", "x") in local_only.touched


# ------------------------------------------------------------------ 接上游
@pytest.mark.parametrize("ns", ["", "*"])
def test_the_same_three_inputs_are_refused_on_the_upstream_path(upstream_on, ns):
    client, store = upstream_on
    with pytest.raises(ValueError):
        gateway.delete_namespace(ns)
    with pytest.raises(ValueError):
        gateway.delete_source(ns, "x")
    assert client.calls == [], "护栏挪回分支里就会看见这条：还没拒就先发了上游"
    assert store.touched == []


def test_valid_namespace_still_routes_upstream(upstream_on):
    client, store = upstream_on
    assert gateway.delete_namespace("webapp-chat") == 1
    assert client.calls
    assert store.touched == []


def test_guard_text_matches_the_upstream_wording(local_only):
    """措辞和上游 `_checked_namespace` 对齐不是讲究：UI 侧 pattern-match 一句
    就够了，不用因为路由变了一句话就得改两处。"""
    with pytest.raises(ValueError) as exc:
        gateway.delete_namespace("")
    assert "namespace" in str(exc.value) and "refusing to delete" in str(exc.value)
