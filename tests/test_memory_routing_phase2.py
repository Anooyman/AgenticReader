"""Phase 2 · 收敛三路线的测试面（PLAN-MEMORY-CONVERGENCE.md 阶段 2 + lead 分工）。

沿用 Phase 1 的注入面：假 MemoryClient 进 upstream._client 模块全局；本地路
一律 monkeypatch 到记录型 stub，任何"上游开着却静默落本地"的回归都会打在
计数断言上。语义口径：
  * 删除面走"写不回落"——失败 raise，不许悄悄换成 local 删一遍了事；
  * brief 轻量入库上游态走 ingest(source_type=brief, namespace=AATF)，
    source_id=item_id 形状原样传下去，"已加载"判定按 source_id 幂等；
  * unset env 的一切都是今天的行为，这条底线从 Phase 1 保到 Phase 2。
"""
import asyncio
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.memory import gateway  # noqa: E402
from src.memory import upstream  # noqa: E402


def _run(x):
    if hasattr(x, "__await__"):
        return asyncio.run(x)
    return x


class _Phase2Client:
    """Phase 2 的假上游：delete/delete_where 带 scope 守卫，ingest 按
    (namespace, source_id) 记住已入库集合做 echo-dedup，namespaces() 给
    上游侧计数——全是上游补丁落地后的真实形状（14/14 探针对过的那套）。"""

    def __init__(self, echo_source_id=None, fail_deletes=False):
        self.delete_calls = []
        self.delete_where_calls = []
        self.ingest_calls = []
        self._seen = {}          # namespace -> {source_id: True}
        self.echo_source_id = echo_source_id
        self.fail_deletes = fail_deletes
        self.upstream_namespaces = [{"name": "upstream-only-ns", "row_count": 7}]

    # ---------------- 写 ----------------
    def ingest(self, path, source_type, *, namespace=None, source_id=None,
               dry_run=False, **kw):
        bucket = self._seen.setdefault(str(namespace), set())
        first = source_id not in bucket if source_id else True
        if source_id:
            bucket.add(source_id)
        added = 1 if first else 0
        self.ingest_calls.append({"path": str(path), "source_type": source_type,
                                  "namespace": namespace, "source_id": source_id})
        echo = (self.echo_source_id if self.echo_source_id is not None
                else source_id)
        return {"source_type": source_type, "namespace": namespace,
                "source_id": echo,
                "report": {"chunks_added": added, "chunks_skipped": 1 - added}}

    # ---------------- 删 ----------------
    def delete(self, memory_id):
        if self.fail_deletes:
            raise RuntimeError("上游 delete 炸了")
        self.delete_calls.append(memory_id)
        return {"deleted": 1}

    def delete_where(self, namespace=None, source_id=None, **kw):
        if not namespace and not source_id:
            raise ValueError("delete_where refuses an unscoped delete")
        if self.fail_deletes:
            raise RuntimeError("上游 delete_where 炸了")
        self.delete_where_calls.append({"namespace": namespace, "source_id": source_id})
        return {"deleted": 3}

    # ---------------- 读 ----------------
    def namespaces(self):
        return list(self.upstream_namespaces)

    def status(self, namespace=None):
        return {"namespaces": {e["name"]: e["row_count"] for e in self.upstream_namespaces},
                "total": sum(e["row_count"] for e in self.upstream_namespaces)}

    def search(self, query, namespace=None, namespaces=None, **kw):
        return {"status": "ok", "results": [], "answer": ""}


class _LocalStoreSpy:
    """本地 _store 的记录替身：删了几条、有哪些行，一眼见分晓。"""
    rows = [{"id": "x1", "namespace": "ai-research", "source_id": "doc-a",
             "chunk_hash": "h1"},
            {"id": "x2", "namespace": "ai-research", "source_id": "doc-a",
             "chunk_hash": ""}]

    def __init__(self, *a, **kw):
        self.deleted = []

    def rows_for_source(self, ns, sid):
        return [r for r in _LocalStoreSpy.rows if r["source_id"] == sid]

    def all_rows(self, ns):
        return list(_LocalStoreSpy.rows)

    def delete(self, row_id):
        self.deleted.append(row_id)


@pytest.fixture()
def p2_on(monkeypatch, tmp_path):
    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    client = _Phase2Client()
    monkeypatch.setattr(upstream, "_client", client)
    # 本地路全副武装成 spies——上游态下的任何本地动作都是回归
    store = _LocalStoreSpy()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: store)
    return client, store


# ---------------------------------------------------------------- ① 删除三面
def test_delete_item_routes_to_upstream(p2_on):
    client, store = p2_on
    _run(gateway.delete_item("x1"))
    assert client.delete_calls == ["x1"], "delete_item 没走上游"
    assert store.deleted == [], "delete_item 静默落回了本地库"


def test_delete_source_scoped_pair(p2_on):
    client, store = p2_on
    n = _run(gateway.delete_source("ai-research", "doc-a"))
    assert isinstance(n, int)
    assert client.delete_where_calls == [
        {"namespace": "ai-research", "source_id": "doc-a"}], \
        "delete_source 的 scope 组合传得不对"
    assert store.deleted == [], "delete_source 静默落回了本地库"


def test_delete_namespace_scoped_only(p2_on):
    client, store = p2_on
    n = _run(gateway.delete_namespace("ai-research"))
    assert isinstance(n, int)
    calls = client.delete_where_calls
    assert calls and calls[-1]["namespace"] == "ai-research"
    assert not calls[-1].get("source_id"), "delete_namespace 不该带 source_id"
    assert store.deleted == [], "delete_namespace 静默落回了本地库"


def test_delete_unscoped_is_rejected(p2_on):
    """unscoped 的删除请求必须死在守卫上，不许退化成"删全库"或悄悄
    转投本地。"""
    client, store = p2_on
    with pytest.raises(Exception):
        _run(gateway.delete_namespace(""))
    assert store.deleted == [], "unscoped 失败后被本地兜了底"


def test_delete_failure_raises_not_falls_back(p2_on, monkeypatch):
    """与写路同构的失败语义：上游炸了就把 RuntimeError 抛出去，
    本地一行都不该跟着删。"""
    client = _Phase2Client(fail_deletes=True)
    monkeypatch.setattr(upstream, "_client", client)
    store = _LocalStoreSpy()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: store)
    with pytest.raises(RuntimeError):
        _run(gateway.delete_source("ai-research", "doc-a"))
    assert store.deleted == [], "上游写败后回落了本地——Phase 1 写语义的禁脔"


def test_delete_unset_env_stays_local(monkeypatch):
    """回归底线：unset 时删除还是今天的本地逐删，形状一个字节都没变。"""
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.setattr(upstream, "_client", None)
    store = _LocalStoreSpy()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: store)
    n = gateway.delete_source("ai-research", "doc-a")
    assert n == 2 and store.deleted == ["x1", "x2"]


# ---------------------------------------------------------------- ② brief 轻量入库
CARD_SRC = {"pdf": [{"item_id": "card-one", "title": "论文导读一",
                     "summary": "内容一", "date": "2026-11-19",
                     "url": "https://example.org/one.pdf"}],
            "web": [{"item_id": "card-two", "title": "网页导读二",
                     "summary": "内容二", "date": "2026-11-19",
                     "url": "https://example.org/two"}]}


def _stub_parsing(monkeypatch):
    """parse_briefs_dir / LLMBase / VectorStore 三处函数级 import 全换成
    记录 stub——brief 路由测试只该关心"写去了哪"，不该拖解析和 embedding。"""
    import src.pipeline.briefs_parser as bp

    monkeypatch.setattr(bp, "parse_briefs_dir",
                        lambda d, day: {k: [dict(c) for c in v]
                                        for k, v in CARD_SRC.items()})

    class _Emb:
        async def aembed_query(self, text):
            return [0.1, 0.2, 0.3]

    class _StubLLM:
        embedding_model = _Emb()

        def __init__(self, provider=None, **kw):
            pass

    import src.core.llm as core_llm
    monkeypatch.setattr(core_llm, "LLMBase", _StubLLM)

    added = []

    class _StubStore:
        def __init__(self, *a, **kw):
            pass

        def rows_for_source(self, ns, sid):
            return []

        def delete(self, rid):
            pass

        def add(self, rec):
            added.append(rec)

    import src.memory.vector_store as vs_mod
    monkeypatch.setattr(vs_mod, "VectorStore", _StubStore)
    # 坑点（同类 import 时序陷阱，CLAUDE.md Testing Notes 有同款记录）：
    # brief_ingest 在**模块级**绑定 VectorStore——若该模块在本测试之前已被
    # 其它用例 import 过，patch src.memory.vector_store.VectorStore 就够不着
    # 它自己名字空间里的那份，会漏网成真库写入。这里连绑定一起换。
    import src.memory.brief_ingest as bi
    monkeypatch.setattr(bi, "VectorStore", _StubStore)
    # 上游路会把每张卡写成中转 JSON（_stage_brief_card → MEMORY_STAGING_DIR
    # =DATA_ROOT/memory_staging/brief）——不挪进 tmp 就会往仓库真实 data/ 里
    # 落测试垃圾。
    staging = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(bi, "MEMORY_STAGING_DIR", str(staging))
    return added


def test_brief_load_routes_to_upstream_ingest(p2_on, monkeypatch):
    client, store = p2_on
    _stub_parsing(monkeypatch)
    out = _run(gateway.load_brief_date("2026-11-19"))
    assert isinstance(out, dict) and {"loaded", "skipped", "errors"} <= set(out)
    ids = {c["source_id"] for c in client.ingest_calls}
    assert ids == {"card-one", "card-two"}, \
        f"source_id=item_id 没有原样传下去：{sorted(i for i in ids if i)}"
    for call in client.ingest_calls:
        assert call["source_type"] == "brief"
        assert call["namespace"] == "AATF"
    assert store.deleted == []  # 上游态下本地库不该被动


def test_brief_load_repeated_idempotent_by_source_id(p2_on, monkeypatch):
    """"今天早灌过了"的判定：第二遍每张卡的 source_id 都在上游已入库
    集合里 → 0 新增 → loaded False + skipped True（job_runner 靠这俩
    出"已是最新"文案，不许翻成失败或假成功）。"""
    client, store = p2_on
    _stub_parsing(monkeypatch)
    first = _run(gateway.load_brief_date("2026-11-19"))
    assert first["loaded"] is True, f"首灌应算 loaded：{first}"
    n_ingest_first = len(client.ingest_calls)
    again = _run(gateway.load_brief_date("2026-11-19"))
    assert again["loaded"] is False and again["skipped"] is True, again
    assert again["errors"] == []
    assert len(client.ingest_calls) > n_ingest_first or n_ingest_first == 2, \
        "幂等判定绕过了 source_id——重复入库根本没递到上游"


def test_brief_load_unset_env_still_local(monkeypatch):
    """回归底线原样保：unset 时 load_brief_date 还是本地直写，
    store.add 收到的 source_type/source_id 形状不变。"""
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_BRIEF_DRIVER", raising=False)
    monkeypatch.setattr(upstream, "_client", None)
    added = _stub_parsing(monkeypatch)
    out = _run(gateway.load_brief_date("2026-11-19"))
    assert out["loaded"] is True
    assert {r["source_id"] for r in added} == {"card-one", "card-two"}
    assert all(r["source_type"] == "brief" for r in added)
    assert all(r["namespace"] == "AATF" for r in added)


# ---------------------------------------------------------------- ③ source_id echo
def test_source_id_echo_mismatch_warns(p2_on, monkeypatch, caplog):
    """上游 adapter 若把 source_id 派生成别的值，gateway 必须 warning
    点名两边——这题从 Phase 1 的"探测不到"升级成 Phase 2 的"真递上了
    还不一致"。"""
    client = _Phase2Client(echo_source_id="derived-9")
    monkeypatch.setattr(upstream, "_client", client)
    doc = pathlib.Path("/tmp/whatever.json")
    with caplog.at_level("WARNING"):
        _run(gateway.ingest(str(doc), "ai_research", "ai-research",
                            source_id="req-1"))
    blob = caplog.text
    assert "derived-9" in blob and "req-1" in blob, \
        "echo 不匹配没有点名两边的 warning"


def _ns_names(out) -> set:
    # 本地条目的键是 "namespace"（memory_browse._build_overview），上游并入
    # 条目用哪个键还要等落地——两种键都认，名字在场才是本用例的断言。
    return {n.get("name") or n.get("namespace") for n in out.get("namespaces", [])}


# ---------------------------------------------------------------- ④ 计数层并
def test_overview_sees_both_sides(p2_on):
    """"两边都算得见"：fetch_overview 的 namespaces 里本地行和上游
    namespaces() 都得现身，计数别互相顶掉。"""
    from src.ui.backend.services import memory_browse
    client, store = p2_on
    out = _run(memory_browse.fetch_overview())
    names = _ns_names(out)
    assert "upstream-only-ns" in names, f"上游计数没并进来：{names}"
    assert "ai-research" in names, f"本地计数被上游顶掉了：{names}"


def test_overview_unaffected_when_upstream_down(monkeypatch):
    """路由不连通 = 计数层退回纯本地旧形状，不许端出半截上游数据。"""
    from src.ui.backend.services import memory_browse
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.setattr(upstream, "_client", None)
    store = _LocalStoreSpy()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: store)
    out = _run(memory_browse.fetch_overview())
    names = _ns_names(out)
    assert names == {"ai-research"}
    assert "upstream-only-ns" not in names
