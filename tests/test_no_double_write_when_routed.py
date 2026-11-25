"""接上上游之后，**本地那条路必须一次都不被调用**。

这条比一般的"路由对不对"更要紧。`_route_is_upstream()` 说 True 只证明
"这一趟会去叫上游"，它并不证明"这一趟也顺便叫了本地"——而后者才是真正会
出事的：同一份内容两处落库，水位线还照往前推，从此再没人能说清哪个库是真的。
收敛文档里那句"半批进上游、半批进旧库是最难收场的局面"，防的就是这个形状，
所以这里钉的是**否**，不是是：

* 三条写通道（ingest / load_brief_date / chat 那侧走的就是 ingest）接上游时，
  本地实现一次都不许进；
* 上游可用却写失败时，gateway 必须把失败抛出去，本地同样一次不补；
* delete 接上游时，本地 store 不得被打开过。

用"叫一次就记一笔"的哨兵函数来测，不用形状差不多的替身——记不到才是这里
要看的信号。
"""
import asyncio

import pytest

import src.memory.brief_ingest as brief_ingest
import src.memory.gateway as gateway
import src.memory.upstream as upstream


class _Spy:
    """每次被调用都往自己的账本里加一笔。"""

    def __init__(self, name, ret=None):
        self.name = name
        self.calls = []
        self.ret = ret if ret is not None else {"chunks_added": 1, "chunks_skipped": 0,
                                                "chunks_deleted": 0}

    def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        return self.ret

    async def coro(self, *a, **kw):
        self.calls.append((a, kw))
        return self.ret

    @property
    def count(self):
        return len(self.calls)


class _StoreSpy:
    """本地库一旦被 new 出来，这些方法就是它的手。"""

    def __init__(self):
        self.touched = []

    def add(self, *a, **kw):
        self.touched.append("add")
        return 1

    def delete(self, *a, **kw):
        self.touched.append("delete")
        return 1

    def all_rows(self, *a, **kw):
        self.touched.append("all_rows")
        return []

    def rows_for_source(self, *a, **kw):
        self.touched.append("rows_for_source")
        return []


class _Up:
    """够用的上游替身：写成功 / 写失败都由测试指定。"""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def _fold(self, tag):
        if self.fail:
            raise ValueError(f"{tag} 失败：上游那边就是没成")
        return {"status": "ok"}

    def ingest(self, path, source_type, *, namespace=None, dry_run=False, **kw):
        self.calls.append(("ingest", str(path), namespace))
        return self._fold("ingest")

    def delete_where(self, namespace=None, namespaces=None, source_type=None,
                     source_id=None, tier=None, cwd=None, dry_run=False):
        self.calls.append(("delete_where", namespace, source_id))
        return {"status": "ok", "deleted": 2}

    def delete(self, ids=None, namespace=None, namespaces=None, cwd=None):
        self.calls.append(("delete", ids, namespace))
        return {"status": "ok", "deleted": 1}

    def all_rows(self, **kw):
        self.calls.append(("all_rows",))
        return {"rows": [], "total": 0, "truncated": False}

    def search(self, query, namespace=None, namespaces=None, **kw):
        self.calls.append(("search", query))
        return {"status": "ok", "results": [], "answer": ""}


def _live(monkeypatch, tmp_path, client):
    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    monkeypatch.setattr(upstream, "_client", client)
    store = _StoreSpy()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: store)
    return store


# ------------------------------------------------------------------ 三条写通道
def test_ingest_routed_never_calls_the_local_implementation(monkeypatch, tmp_path):
    up = _Up()
    store = _live(monkeypatch, tmp_path, up)
    local = _Spy("local_ingest")
    monkeypatch.setattr(gateway, "_ingest_source", lambda *a, **kw: local.coro(*a, **kw))

    doc = tmp_path / "s.json"
    doc.write_text('{"q":"x"}', encoding="utf-8")
    asyncio.run(gateway.ingest(str(doc), "ai_research", "ai-research", source_id="d1"))

    assert up.calls and up.calls[0][0] == "ingest"
    assert local.count == 0, f"接上游还顺手写了本地：{local.calls}"
    assert store.touched == []


def test_brief_load_routed_never_calls_the_local_brief_writer(monkeypatch, tmp_path):
    up = _Up()
    store = _live(monkeypatch, tmp_path, up)
    local = _Spy("load_brief_date_local")
    monkeypatch.setattr(brief_ingest, "load_brief_date_local",
                        lambda *a, **kw: local.coro(*a, **kw))

    asyncio.run(gateway.load_brief_date("2026-11-23"))
    assert local.count == 0, "卡片进了上游，同时又写了一份本地"
    assert store.touched == []


def test_delete_routed_never_opens_the_local_store(monkeypatch, tmp_path):
    up = _Up()
    store = _live(monkeypatch, tmp_path, up)
    assert gateway.delete_source("webapp-chat", "session-1") == 2
    assert up.calls
    assert store.touched == [], "本地库被打开过，双删就是下一次双写的前奏"


# ------------------------------------------------------------------ 失败也不补
def test_a_failed_upstream_write_leaves_nothing_behind(monkeypatch, tmp_path):
    """这条是整个文件的重点：`ingest` 上游可用却写挂了，如果此时顺手补一份
    本地，那才是收敛里最难收场的局面——两边各有半批，水位线照推。"""
    up = _Up(fail=True)
    store = _live(monkeypatch, tmp_path, up)
    local = _Spy("local_ingest")
    monkeypatch.setattr(gateway, "_ingest_source", lambda *a, **kw: local.coro(*a, **kw))

    doc = tmp_path / "s.json"
    doc.write_text('{"q":"x"}', encoding="utf-8")
    with pytest.raises(Exception):
        asyncio.run(gateway.ingest(str(doc), "ai_research", "ai-research", source_id="d1"))

    assert local.count == 0, "写挂了还补了本地——那就是把双写包装成了容错"
    assert store.touched == []


def test_delete_failure_also_leaves_local_alone(monkeypatch, tmp_path):
    class _FailingUp(_Up):
        def delete_where(self, **kw):
            raise ValueError("上游 delete_where 没成")

    store = _live(monkeypatch, tmp_path, _FailingUp())
    with pytest.raises(RuntimeError):
        gateway.delete_source("webapp-chat", "session-1")
    assert store.touched == []


# ------------------------------------------------------------------ 对照
def test_the_same_calls_do_use_the_local_path_when_unrouted(monkeypatch, tmp_path):
    """反面对照，免得这组断言只是"全都别跑"：没接上游时，本地实现**应该**被
    调用，否则前面那些"一次都不许"就只是死掉的代码在自我表扬。"""
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    monkeypatch.setattr(upstream, "_client", None)
    store = _StoreSpy()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: store)
    local = _Spy("local_ingest")
    monkeypatch.setattr(gateway, "_ingest_source", lambda *a, **kw: local.coro(*a, **kw))

    asyncio.run(gateway.ingest("/tmp/x.json", "ai_research", "ai-research"))
    assert local.count == 1, "未接上游时本地这条才是正路"
