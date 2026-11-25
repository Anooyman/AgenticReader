"""`MEMORY_STORE_MODE=upstream`：把"旧 workflow"这条退路明着关掉。

`auto` 是开发机上最舒服的档位——上游挂了还能继续用本地旧库跑着。但"放弃之前的
workflow"这句话如果是当真的，就得有个档位能让**回落本身变成错误**，而不是每条
调用点各自小心。差口从来不是路由接错了造出来的，是"这次上游没通，那先写本地"
造出来的：一次回落没人记得，攒下来就是一库谁都不认的旧行。

这一档就是干这个的，所以用例只钉两件事：

* 上游不在了——**每条**路都得抛，一条都不许悄悄落到本地；
* 上游在——行为和 auto 走上游时一字不差，别把"要求严格"做成"多此一举"。

另外 `local` 这把 kill switch 仍然是有效的逃生口：这档不是"不许有备用方案"，
是"不许没有备用方案却装作有"。
"""
import asyncio

import pytest

import src.memory.gateway as gateway
import src.memory.upstream as upstream


class _UpClient:
    """够用的 SDK 替身：search 给一行，browse 给一行，ingest 报"新增 1 个 chunk"。"""

    def __init__(self):
        self.calls = []

    def search(self, query, namespace=None, namespaces=None, deadline_s=None, **kw):
        self.calls.append(("search", query))
        return {"status": "ok",
                "results": [{"id": "u1", "namespace": "ai-research", "tier": "mid",
                             "abstract": "上游的答案", "detail": "", "keywords": "",
                             "created_at": "2026-11-20T00:00:00+00:00",
                             "occurred_at": "2026-11-20T00:00:00+00:00",
                             "source_id": "doc-1", "source_type": "ai_research",
                             "chunk_hash": "aa", "score": 0.7}],
                "answer": "上游答案"}

    def all_rows(self, namespace=None, namespaces=None, source_id=None, limit=None,
                 columns=None, tier=None, cwd=None):
        self.calls.append(("all_rows", namespace, namespaces))
        return {"rows": [{"id": "u1", "namespace": "ai-research", "source_id": "doc-1",
                          "source_type": "ai_research", "chunk_hash": "aa",
                          "abstract": "a", "detail": "", "keywords": "[]",
                          "created_at": "2026-11-20T00:00:00+00:00",
                          "occurred_at": "2026-11-20T00:00:00+00:00"}],
                "total": 1, "returned": 1, "truncated": False, "scoped": True,
                "namespaces": ["ai-research"], "store_dir": "/up"}

    def rows_for_source(self, namespace=None, namespaces=None, source_id="", limit=None,
                        columns=None, cwd=None):
        self.calls.append(("rows_for_source", namespace, namespaces, source_id))
        return self.all_rows(namespace=namespace, namespaces=namespaces)

    def ingest(self, path, source_type, *, namespace=None, dry_run=False, **kw):
        self.calls.append(("ingest", str(path), source_type, namespace))
        return {"status": "ok", "report": {"units": 1, "chunks_total": 1,
                                          "chunks_added": 1, "chunks_skipped": 0,
                                          "chunks_deleted": 0, "stale_kept": 0,
                                          "chunks_failed": [], "summary_id": "s1",
                                          "dry_run": dry_run}}

    def delete(self, ids=None, namespace=None, namespaces=None, cwd=None):
        self.calls.append(("delete", ids, namespace))
        return {"status": "ok", "deleted": 1}

    def delete_where(self, namespace=None, namespaces=None, source_type=None,
                     source_id=None, tier=None, cwd=None, dry_run=False):
        self.calls.append(("delete_where", namespace, namespaces, source_id))
        return {"status": "ok", "deleted": 1}


class _LocalStore:
    """本地旧库——被碰一下就记一笔。"""

    def __init__(self, sink):
        self.sink = sink

    def search(self, *a, **kw):
        self.sink.append("local.search")
        return []

    def all_rows(self, namespace):
        self.sink.append("local.all_rows")
        return [{"id": "l1", "chunk_hash": "h", "source_id": "x", "occurred_at": ""}]

    def rows_for_source(self, namespace, source_id):
        self.sink.append("local.rows_for_source")
        return []

    def delete(self, row_id):
        self.sink.append("local.delete")
        return 1

    def delete_source(self, namespace, source_id):
        self.sink.append("local.delete_source")
        return 1

    def delete_namespace(self, namespace):
        self.sink.append("local.delete_namespace")
        return 1


@pytest.fixture()
def upstream_down(monkeypatch, tmp_path):
    """`MEMORY_STORE_MODE=upstream` + 上游根本不可达，本地库全部记流水账。"""
    monkeypatch.setenv("MEMORY_STORE_MODE", "upstream")
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.setattr(upstream, "_client", None)
    sink = []
    monkeypatch.setattr(gateway, "_store", lambda provider=None: _LocalStore(sink))
    return sink


@pytest.fixture()
def upstream_live(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_STORE_MODE", "upstream")
    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    client = _UpClient()
    monkeypatch.setattr(upstream, "_client", client)
    sink = []
    monkeypatch.setattr(gateway, "_store", lambda provider=None: _LocalStore(sink))
    return client, sink


# ------------------------------------------------------------------ 不可达：必须抛

@pytest.mark.parametrize("op", [
    "search", "ingest", "browse", "rows_for_source",
    "delete_item", "delete_source", "delete_namespace",
])
def test_every_path_fails_loudly_instead_of_touching_local(upstream_down, op):
    sink = upstream_down
    with pytest.raises(RuntimeError) as exc:
        if op == "search":
            asyncio.run(gateway.search("q", namespaces="ai-research"))
        elif op == "ingest":
            asyncio.run(gateway.ingest("/tmp/file.json", "ai_research",
                                       namespace="ai-research", source_id="doc-1"))
        elif op == "browse":
            gateway.browse_all_rows("ai-research")
        elif op == "rows_for_source":
            gateway.browse_rows_for_source("ai-research", "doc-1")
        elif op == "delete_item":
            gateway.delete_item("row-1")
        elif op == "delete_source":
            gateway.delete_source("ai-research", "doc-1")
        else:
            gateway.delete_namespace("ai-research")
    assert "upstream" in str(exc.value)
    assert sink == [], f"{op} 抛了，可它抛之前已经往本地写了一笔：{sink}"


# ------------------------------------------------------------------ 可达：与 auto 无异

def test_reachable_upstream_behaves_exactly_like_the_routed_path(upstream_live):
    client, sink = upstream_live
    rows = gateway.browse_all_rows("ai-research")
    assert [r["id"] for r in rows] == ["u1"]
    assert client.calls and client.calls[0][0] == "all_rows"

    hits = asyncio.run(gateway.search("q", namespaces="ai-research"))
    got = hits.get("results") if isinstance(hits, dict) else hits
    assert any((r.get("abstract") == "上游的答案") for r in (got or [])), hits
    assert any(c[0] == "search" for c in client.calls)

    assert gateway.delete_source("ai-research", "doc-1") == 1
    assert sink == [], "这一档下本地库一次都不该被碰"


def test_ingest_under_this_mode_writes_nothing_local(upstream_live):
    client, sink = upstream_live
    report = asyncio.run(gateway.ingest("/tmp/file.json", "ai_research",
                                        namespace="ai-research", source_id="doc-1"))
    assert report["chunks_added"] == 1
    assert any(c[0] == "ingest" for c in client.calls)
    assert sink == []


def test_the_kill_switch_still_wins_when_explicitly_set(monkeypatch, tmp_path):
    """`local` 仍是有效逃生口——这档不是"不许有备用方案"，而是"不许没有
    备用方案却装作有"。所以两个开关同时存在时，local 必须说话最大声。"""
    monkeypatch.setenv("MEMORY_STORE_MODE", "local")
    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    client = _UpClient()
    monkeypatch.setattr(upstream, "_client", client)
    sink = []
    monkeypatch.setattr(gateway, "_store", lambda provider=None: _LocalStore(sink))
    gateway.browse_all_rows("ai-research")
    assert sink == ["local.all_rows"]
    assert client.calls == []


def test_default_mode_is_unchanged_by_the_new_option(monkeypatch, tmp_path):
    """加一档不许动到既有的默认行为：不设这个变量时，上游不可达仍是
    "warning + 本地"，不是抛错。"""
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.setattr(upstream, "_client", None)
    sink = []
    monkeypatch.setattr(gateway, "_store", lambda provider=None: _LocalStore(sink))
    assert gateway.browse_all_rows("ai-research") == [{"id": "l1", "chunk_hash": "h",
                                                      "source_id": "x",
                                                      "occurred_at": ""}]
    assert sink == ["local.all_rows"]


def test_config_accepts_the_new_value_and_still_rejects_garbage():
    import os

    from src.memory import config
    for raw, want in (("upstream", "upstream"), ("  UPSTREAM ", "upstream"),
                      ("upstream-only", config.MEMORY_MODE_AUTO)):
        os.environ["MEMORY_STORE_MODE"] = raw
        try:
            assert config.get_memory_store_mode() == want, raw
        finally:
            os.environ.pop("MEMORY_STORE_MODE", None)
