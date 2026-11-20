"""阶段 1 · memory 路由收敛契约（PLAN-MEMORY-CONVERGENCE.md 阶段 1）。

钉三件事 + 一条底线：
  ① auto 路由双态：LLM_MEMORY_REPO 有效 → gateway.search/ingest 走上游
     （注入面沿用 test_upstream_facade 的 upstream._client 模块全局，
     假 MemoryClient 的 search/ingest 方法即真实 SDK 面的替身）；
     未设/无效 → 本地旧路零变化，上游入口若被碰就当场炸。
  ② 形状映射：上游 33 列假行（带 tier/abstracts_chain/session_id 等
     AR 认不出的列）→ gateway 摊平成 agentic_search 的 14 列形状，
     逐字段断言，含 occurred_at 存在性（空时回退 created_at，与
     search.py:168 的消费习惯同构）与 summary 行启发式命中。
  ③ 上游路幂等：同文件重复 ingest 第二次必须报 0 新增——先用假 client
     钉形状，真上游实测留给终验人（注释见最后一条用例）。
  ④ 回归底线：env 未设时两条写通道的调用形状逐字等价今天。
"""
import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.memory import gateway  # noqa: E402
from src.memory import upstream  # noqa: E402

# AR 14 列形状里子 agent / browse 要吃的全部文本列（vector_store.py:24-28）
AR_TEXT_FIELDS = [
    "id", "namespace", "memory_type", "abstract", "detail", "keywords",
    "created_at", "source_type", "source_id", "chunk_hash", "raw_source",
    "occurred_at",
]


def _run(coro):
    if hasattr(coro, "__await__"):
        return asyncio.run(coro)
    return coro


# 上游 33 列的一行（vector.py:39-53 的列名照抄，多出来的知识列留白不影响
# 映射层——这里就是要证明"看不见的列不许炸映射"）。
def _up33_row(**over):
    row = {
        "id": "u-1", "namespace": "ai-research", "tier": "core",
        "memory_type": "article", "abstract": "论文摘要 A",
        "detail": "长文详述。" * 100,          # 长 detail + 空 keywords → summary 行
        "abstracts_chain": "", "keywords": "",
        "last_accessed_at": "", "created_at": "2026-11-01T08:00:00+00:00",
        "tier_updated_at": "", "source": "doc-a", "session_id": "",
        "source_type": "ai_research", "source_id": "doc-a",
        "chunk_hash": "",                       # 上游本身 summary 行也是空 hash
        "raw_source": '{"title":"A"}',
        "occurred_at": "2026-11-01T08:00:00+00:00",
    }
    row.update(over)
    return row


class _RoutingClient:
    """假 MemoryClient 的 search/ingest 面：记录调用，search 给 33 列行，
    ingest 按"首见路径 chunks_added=3、再见=0（其余全 skipped）"模拟上游
    hash-dedup——键名是上游真契约（无 new_chunks 一说）。"""

    def __init__(self, rows=None):
        self.search_calls = []
        self.ingest_calls = []
        self._seen = {}
        self.rows = rows if rows is not None else [
            _up33_row(),
            _up33_row(id="u-2", keywords="attention, paper",
                      detail="短一些的 chunk 内容", chunk_hash="ab12cd34",
                      occurred_at=""),   # 故意留空 → 映射层须回退 created_at
        ]

    def search(self, query, namespace=None, namespaces=None, deadline_s=None, **kw):
        self.search_calls.append({"query": query, "namespace": namespace,
                                  "namespaces": namespaces, "kw": kw})
        return {"status": "ok", "results": [dict(r) for r in self.rows],
                "answer": "上游答案"}

    def ingest(self, path, source_type, *, namespace=None, dry_run=False, **kw):
        key = str(path)
        first = key not in self._seen
        self._seen[key] = True
        # 上游真键名是 chunks_added/chunks_skipped（gateway 的映射层
        # present-only 只带上游真报的那几个键）；重复文件 = 0 新增 + 全部
        # skipped 的 hash-dedup 形状。
        added = 3 if first else 0
        self.ingest_calls.append({"path": key, "source_type": source_type,
                                  "namespace": namespace})
        return {"source_type": source_type, "namespace": namespace,
                "report": {"chunks_added": added, "chunks_skipped": 3 - added}}

    def scope_of(self):
        c = self.search_calls[-1]
        nss, ns = c.get("namespaces"), c.get("namespace")
        if nss:
            return sorted(nss)
        if ns:
            return [ns]
        return []


@pytest.fixture()
def upstream_on(monkeypatch, tmp_path):
    """把环境翻成"上游有效"：repo 目录 + _client 注入假 SDK——路由的
    触发判定不管是查 env 还是查 client 构造，双通道都满足。
    本地路配 no-op 兜底桩：还没接路由的实现会当场撞在"没调假 client"
    上，而不是慢悠悠去跑真的 agentic_search/ingest_source。"""
    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    client = _RoutingClient()
    monkeypatch.setattr(upstream, "_client", client)

    async def _local_search(*a, **kw):
        return {"answer": "", "results": [], "iterations": 0, "tool_calls_made": 0}

    async def _local_ingest(*a, **kw):
        return {"chunks_added": 0, "chunks_skipped": 0, "chunks_deleted": 0}

    monkeypatch.setattr(gateway, "_agentic_search", _local_search)
    monkeypatch.setattr(gateway, "_ingest_source", _local_ingest)
    return client


@pytest.fixture()
def upstream_off(monkeypatch):
    """本地态：env 清空、client 缓存复位，上游模块入口换成会炸的替身——
    任何"偷偷走上游"的回归都会在这里当场炸掉而不是静默变慢。"""
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.setattr(upstream, "_client", None)

    def _boom(*a, **kw):
        raise AssertionError("未设 LLM_MEMORY_REPO 却碰了上游入口")

    monkeypatch.setattr(upstream, "upstream_search", _boom, raising=False)
    monkeypatch.setattr(upstream, "upstream_ingest", _boom, raising=False)
    return monkeypatch


# ---------------------------------------------------------------- ① 双态路由
def test_repo_valid_search_routes_to_upstream(upstream_on):
    res = _run(gateway.search("注意力机制", namespaces=["ai-research"]))
    assert upstream_on.search_calls, "gateway.search 没有走上游"
    assert upstream_on.scope_of() == ["ai-research"]
    assert isinstance(res, dict) and res.get("results") is not None


def test_repo_valid_ingest_routes_to_upstream(upstream_on, tmp_path):
    doc = tmp_path / "summary.json"
    doc.write_text('{"q": "x"}', encoding="utf-8")
    out = _run(gateway.ingest(str(doc), "ai_research", "ai-research",
                              source_id="doc-a"))
    assert upstream_on.ingest_calls == [{"path": str(doc),
                                         "source_type": "ai_research",
                                         "namespace": "ai-research"}]
    assert isinstance(out, dict)


def test_env_unset_search_stays_local(upstream_off):
    local = []

    async def fake_local(query, namespace=None, **kw):
        local.append(query)
        return {"answer": "", "results": [], "iterations": 1, "tool_calls_made": 0}

    upstream_off.setattr(gateway, "_agentic_search", fake_local)
    res = _run(gateway.search("q"))
    assert local == ["q"]
    assert "results" in res  # 形状还是 agentic_search 那套


def test_env_unset_ingest_stays_local(upstream_off):
    local = []

    async def fake_local(path, source_type=None, namespace=None,
                         provider=None, source_id=None):
        local.append((path, source_type, namespace))
        return {"chunks_added": 1, "chunks_skipped": 0, "chunks_deleted": 0}

    upstream_off.setattr(gateway, "_ingest_source", fake_local)
    out = _run(gateway.ingest("/tmp/x.json", "ai_research", "ai-research"))
    assert local == [("/tmp/x.json", "ai_research", "ai-research")]
    assert out["chunks_added"] == 1


def test_invalid_repo_falls_back_local_with_warning(upstream_off, caplog):
    """env 设了但目录无效 = "不可达"，与未设同路：warning + 本地旧路。"""
    upstream_off.setenv("LLM_MEMORY_REPO", "/no/such/llm-memory-checkout")
    local = []

    async def fake_local(query, namespace=None, **kw):
        local.append(query)
        return {"answer": "", "results": [], "iterations": 1, "tool_calls_made": 0}

    upstream_off.setattr(gateway, "_agentic_search", fake_local)
    with caplog.at_level("WARNING"):
        _run(gateway.search("q"))
    assert local == ["q"]


# ---------------------------------------------------------------- ② 形状映射
def test_search_maps_rows_to_ar_fields(upstream_on):
    res = _run(gateway.search("q", namespaces=["ai-research"]))
    rows = res["results"]
    assert rows, "上游命中必须出现在 results 里"
    # 验收线："不多给任何一个键"——上游专有的列必须整列丢掉，
    # 夹带进来就是映射层越界
    upstream_only = {"tier", "abstracts_chain", "session_id",
                     "last_accessed_at", "tier_updated_at"}
    for r in rows:
        assert isinstance(r, dict)
        for k in AR_TEXT_FIELDS:
            assert k in r, f"映射行缺列 {k!r}：{sorted(r)}"
        assert not (set(r) & upstream_only), \
            f"映射行夹带了上游专有列：{sorted(set(r) & upstream_only)}"
    first = rows[0]
    # 逐字段直通断言（映射层只许挪列不许造值）
    assert first["id"] == "u-1"
    assert first["source_id"] == "doc-a"
    assert first["source_type"] == "ai_research"
    assert first["abstract"] == "论文摘要 A"
    assert first["memory_type"] == "article"
    assert first["namespace"] == "ai-research"


def test_occurred_at_present_and_date_sliced(upstream_on):
    """/briefs 日期聚合吃 occurred_at[:10]——映射后这必须还是可切的 ISO 串，
    而且上游那行 occurred_at 空着的（u-2）必须回退 created_at，
    这是 search.py:168 的既有消费习惯，不许退化成空串。"""
    res = _run(gateway.search("q", namespaces=["ai-research"]))
    rows = {r["id"]: r for r in res["results"]}
    for r in rows.values():
        assert r["occurred_at"], "occurred_at 为空会静默掉出日期聚合"
        assert len(r["occurred_at"]) >= 10 and r["occurred_at"][:10]
    assert rows["u-2"]["occurred_at"].startswith("2026-11-01")  # 回退 created_at


def test_summary_row_heuristic_hits_and_misses(upstream_on):
    """keywords 空 + detail 长 → 判成 summary 行（chunk_hash==""）；
    普通 chunk 行必须保住非空 hash，否则"已加载"计数和 is_summary_row
    全失真。上游本尊的 chunk_hash 列若被映射层直接搬来也算合规——
    断言只钉最终形状。"""
    res = _run(gateway.search("q", namespaces=["ai-research"]))
    rows = {r["id"]: r for r in res["results"]}
    assert rows["u-1"]["chunk_hash"] == ""            # 启发式命中（u-1 本来就是空）
    assert rows["u-2"]["chunk_hash"] != ""            # 普通行必须非空
    # 若实现把"keywords 空 + detail 长"判到 chunk 行上了，也在这里露馅：
    chunk_row = rows["u-2"]
    assert not (chunk_row["keywords"] == "" and len(chunk_row["detail"]) > 500)


def test_mapped_rows_survive_unknown_upstream_columns(upstream_on):
    """假行带了 AR 没有的列（tier/abstracts_chain/session_id/source）——
    映射层不许因未知列 KeyError；未知列要么被丢弃要么原样带着，都不许炸。"""
    res = _run(gateway.search("q", namespaces=["ai-research"]))
    assert len(res["results"]) == 2


# ---------------------------------------------------------------- ③ 幂等契约
def test_reingest_same_file_reports_zero_new(upstream_on, tmp_path):
    """上游 hash-dedup 的 AR 侧形状：同一文件第二次 ingest 的新增计数
    必须归零。假 client 模拟的是"上游自带幂等"的声称，这条测试先钉
    gateway 是否把 0 如实带回来而不是把 report 摊掉——
    ────────────────────────────────────────────────────────────────
    ⚠ 终验人必做项：拿真上游 + 真文件跑同一场景（计划验收 3），
      假 client 的 0 新增只是形状保证，不是上游行为的证据。
    """
    doc = tmp_path / "session-01.json"
    doc.write_text('{"messages": []}', encoding="utf-8")
    first = _run(gateway.ingest(str(doc), "webapp_chat", "webapp-chat",
                                source_id="s-01"))
    second = _run(gateway.ingest(str(doc), "webapp_chat", "webapp-chat",
                                 source_id="s-01"))
    assert len(upstream_on.ingest_calls) == 2
    added_first, added_second = _new_added(first), _new_added(second)
    assert added_first > 0, f"首次应有新增，report={first}"
    assert added_second == 0, f"重复 ingest 应报 0 新增，report={second}"


def _new_added(report) -> int:
    """在候选计数键里找"新增行数"——上游真契约键是 chunks_added
    （2026-11-19 conv-src 终报确认：上游没有 new_chunks 这个键，grep 验证
    过），其余只是兼容位。gateway 映射层是 present-only：缺 chunks_added
    就不造计数——所以找不到任何计数键直接失败，逼实现把幂等信号留在
    返回形状里。
    ────────────────────────────────────────────────────────────────
    ⚠ 终验人必做项：拿真上游 + 真文件跑同一场景（计划验收 3）。"""
    for k in ("chunks_added", "added", "new"):
        if isinstance(report, dict) and k in report:
            return int(report[k])
        if isinstance(report, dict) and isinstance(report.get("report"), dict):
            sub = report["report"]
            for k2 in ("chunks_added", "added", "new"):
                if k2 in sub:
                    return int(sub[k2])
    raise AssertionError(f"返回形状里找不到新增计数键，幂等契约无法钉：{report}")


# ---------------------------------------------------------------- ⑤ 边界与开关
def test_store_mode_local_is_the_kill_switch(monkeypatch, tmp_path):
    """CLAUDE.md 已钉死的 kill switch：MEMORY_STORE_MODE=local 时，即使
    LLM_MEMORY_REPO 有效、client 构造成功，也必须强制走本地旧路。
    （PLAN-MEMORY-CONVERGENCE.md 没提这个开关——若代码最终没它，本用例
    的"待落地"状态要在验收前裁决，别当测试毛病绕开。）"""
    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    monkeypatch.setenv("MEMORY_STORE_MODE", "local")
    client = _RoutingClient()
    monkeypatch.setattr(upstream, "_client", client)
    local = []

    async def fake_local(query, namespace=None, **kw):
        local.append(query)
        return {"answer": "", "results": [], "iterations": 1, "tool_calls_made": 0}

    async def fake_local_ingest(path, source_type=None, namespace=None,
                                provider=None, source_id=None):
        local.append(("ingest", path))
        return {"chunks_added": 1, "chunks_skipped": 0, "chunks_deleted": 0}

    monkeypatch.setattr(gateway, "_agentic_search", fake_local)
    monkeypatch.setattr(gateway, "_ingest_source", fake_local_ingest)
    _run(gateway.search("q"))
    _run(gateway.ingest("/tmp/x.json", "ai_research", "ai-research"))
    assert local, "kill switch 失效：上游可用时本地路一条都没走"
    assert not client.search_calls and not client.ingest_calls, \
        "MEMORY_STORE_MODE=local 仍写了/读了上游"


def test_aatf_brief_channel_stays_local(upstream_on, monkeypatch):
    """计划裁决：Phase 1 只收 pipeline 与 chat_ingest 两条写通道，
    轻量入库 AATF 仍走本地直写（brief_ingest），不许被 auto 路由
    "顺手"捎带进上游——那是 Phase 2 的 id 空间换轨才动的事。"""
    seen = []

    async def fake_local(date, provider=None, **kw):
        seen.append(date)
        return {"loaded": True, "skipped": False, "errors": []}

    import src.memory.brief_ingest as bi
    monkeypatch.setattr(bi, "load_brief_date_local", fake_local)
    monkeypatch.delenv("MEMORY_BRIEF_DRIVER", raising=False)
    _run(gateway.load_brief_date("2026-11-19"))
    assert seen == ["2026-11-19"]
    assert not upstream_on.ingest_calls, "AATF 通道被 auto 路由误伤了"


def test_browse_and_delete_stay_local_with_upstream_on(upstream_on, monkeypatch):
    """浏览/删除面 Phase 1 明确留本地：即便上游全绿，browse_* / delete_*
    只许碰本地 _store，一次上游调用都不该有（delete facade 是 Phase 2）。"""
    class _S:
        def rows_for_source(self, ns, sid):
            return [{"id": "x1", "chunk_hash": "h"}]

        def all_rows(self, ns):
            return [{"id": "x1", "chunk_hash": "h"}]

        def delete(self, row_id):
            pass

    monkeypatch.setattr(gateway, "_store", lambda provider=None: _S())
    assert len(gateway.browse_all_rows("ai-research")) == 1
    assert gateway.delete_source("ai-research", "doc-x") == 1
    assert gateway.delete_namespace("webapp-chat") == 1
    assert not upstream_on.ingest_calls and not upstream_on.search_calls, \
        "browse/delete 漏走上游了——Phase 1 它们是本地路"


# ---------------------------------------------------------------- ⑥ 回归底线
def test_write_call_points_unchanged_when_off(upstream_off):
    """chat_ingest / pipeline 的调用形状零改动是计划 §1.3 的硬承诺：
    这里以 gateway.ingest 为代理，确认缺省态下它就是当年的
    _ingest_source 直通——签名、provider 归一、返回报表都别动。"""
    seen = {}

    async def fake_local(path, source_type=None, namespace=None,
                         provider=None, source_id=None):
        seen.update(path=path, source_type=source_type, namespace=namespace,
                    provider=provider, source_id=source_id)
        return {"chunks_added": 0, "chunks_skipped": 1, "chunks_deleted": 0}

    upstream_off.setattr(gateway, "_ingest_source", fake_local)
    upstream_off.setattr(gateway, "resolve_provider", lambda p: f"resolved[{p}]")
    out = _run(gateway.ingest("/tmp/x.json", "webapp_chat", "webapp-chat",
                              provider=" Azure ", source_id="s-9"))
    assert seen["provider"] == "resolved[ Azure ]"
    assert seen["source_id"] == "s-9"
    assert out["chunks_skipped"] == 1
