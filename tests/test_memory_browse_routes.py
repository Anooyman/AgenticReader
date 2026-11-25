"""browse_* 的上游路由（收敛第三格）。

`search()` / `ingest()` / `delete_*` 早就按同一条 auto 规则选路了，只有行级
浏览原语恒本地。这组用例钉的就是刚接上的那一格：

1. **上游有效就走整行面**，一次都不该碰本地库——否则 `/data` 的行列表会画出
   一个"本地还剩几行"的世界，而搜索到的行在上游；
2. **`limit` 必须是 None**：`MemoryClient.all_rows` 有默认封顶
   （`MAX_ROWS_PER_CALL`），照默认走，`/briefs` 的日期格和"已入速览库"徽标
   就会在行数超过封顶时静默少算——这条是防"看着接上了，其实数不对"；
3. **`"*"` 不翻译成某个真实名字**：memory_browse 默认就是这么调的，上游把
   "*" 当"没有 scope 这回事"处理，翻成名字反而缩小了作用域；
4. **读路允许回落但不静默**：上游没成 → warning + 本地，与 `search()` 同口径
   （写路不回落，那是另一组用例的事）；
5. **env 没设时零变化**：本地实现一个字节都不该被这条改动影响。
"""
import logging

import pytest

import src.memory.gateway as gateway
import src.memory.upstream as upstream

# 上游整行面的一行（33 列里 gateway 会取走它要的那 14 个）
_UPSTREAM_ROW = {
    "id": "u-1", "namespace": "ai-research", "tier": "mid", "memory_type": "semantic",
    "abstract": "abstract", "detail": "detail", "abstracts_chain": "[]",
    "keywords": '["k1"]', "created_at": "2026-11-20T10:00:00+00:00",
    "occurred_at": "2026-11-20T10:00:00+00:00", "source_id": "doc-1",
    "source_type": "ai_research", "chunk_hash": "", "raw_source": "raw",
    "importance": 0.5, "access_count": 0, "vector": [0.1, 0.2],
}

_LOCAL_ROW = {"id": "l-1", "namespace": "ai-research", "chunk_hash": "h"}


class _BrowseClient:
    """假上游 SDK：记录 gateway 递下来的作用域参数。"""

    def __init__(self, rows=None, fail=False):
        self.rows = rows if rows is not None else [dict(_UPSTREAM_ROW)]
        self.fail = fail
        self.all_calls = []
        self.source_calls = []

    def _result(self):
        if self.fail:
            raise ValueError("unknown namespace — not in this store")
        return {"rows": list(self.rows), "total": len(self.rows),
                "returned": len(self.rows), "truncated": False,
                "namespaces": None, "scoped": False, "store_dir": "/up/stream"}

    def all_rows(self, **kw):
        self.all_calls.append(kw)
        return self._result()

    def rows_for_source(self, **kw):
        self.source_calls.append(kw)
        return self._result()


class _LocalStore:
    """本地旧库——被碰到就会记账，好让"偷偷留本地"这种回归当场现形。"""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [dict(_LOCAL_ROW)]
        self.all_calls = []
        self.source_calls = []

    def all_rows(self, namespace):
        self.all_calls.append(namespace)
        return list(self.rows)

    def rows_for_source(self, namespace, source_id):
        self.source_calls.append((namespace, source_id))
        return list(self.rows)


@pytest.fixture()
def upstream_on(monkeypatch, tmp_path):
    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    client = _BrowseClient()
    monkeypatch.setattr(upstream, "_client", client)
    return client


@pytest.fixture()
def upstream_on_failing(monkeypatch, tmp_path):
    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    client = _BrowseClient(fail=True)
    monkeypatch.setattr(upstream, "_client", client)
    return client


@pytest.fixture()
def upstream_off(monkeypatch):
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    monkeypatch.setattr(upstream, "_client", None)

    def _boom(*_a, **_kw):
        raise AssertionError("未设 LLM_MEMORY_REPO 却碰了上游浏览面")

    monkeypatch.setattr(upstream, "upstream_browse_all_rows", _boom)
    monkeypatch.setattr(upstream, "upstream_browse_rows_for_source", _boom)
    return None


# ------------------------------------------------------------------ ① 走上游

def test_browse_all_rows_follows_the_route_and_never_touches_local(upstream_on, monkeypatch):
    local = _LocalStore()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: local)

    rows = gateway.browse_all_rows("ai-research")
    assert [r["id"] for r in rows] == ["u-1"]
    assert local.all_calls == [], "browse 还偷偷写本地"
    # 形状是本地那 14 列，不多不少：memory_browse / briefs_data 按这个形状写死
    assert set(rows[0]) == {"id", "namespace", "memory_type", "abstract", "detail",
                            "keywords", "created_at", "occurred_at", "source_type",
                            "source_id", "chunk_hash", "raw_source", "importance",
                            "score"}


def test_the_whole_namespace_is_asked_for_not_a_capped_page(upstream_on, monkeypatch):
    """`limit=None` 是关键断言：默认封顶会让 /briefs 的计数在阈值之上少算，
    而那种偏差不会报错，只会安静地把"已入库"说成"没入库"。"""
    monkeypatch.setattr(gateway, "_store", lambda provider=None: _LocalStore())
    gateway.browse_all_rows(["ai-research", "webapp-chat"])
    assert upstream_on.all_calls, "browse 没有走上游"
    assert upstream_on.all_calls[0].get("limit") is None


def test_wildcard_is_not_translated_into_a_real_name(upstream_on, monkeypatch):
    monkeypatch.setattr(gateway, "_store", lambda provider=None: _LocalStore())
    gateway.browse_all_rows("*")
    sent = upstream_on.all_calls[0]
    assert "namespace" not in sent and "namespaces" not in sent, \
        f"'*' 被翻成了具体名字，作用域被缩小：{sent}"


def test_a_namespace_list_goes_as_namespaces(upstream_on, monkeypatch):
    monkeypatch.setattr(gateway, "_store", lambda provider=None: _LocalStore())
    gateway.browse_all_rows(["ai-research", "webapp-chat"])
    assert upstream_on.all_calls[0].get("namespaces") == ["ai-research", "webapp-chat"]


def test_browse_rows_for_source_follows_the_route(upstream_on, monkeypatch):
    local = _LocalStore()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: local)
    rows = gateway.browse_rows_for_source("ai-research", "doc-1")
    assert [r["id"] for r in rows] == ["u-1"]
    assert local.source_calls == []
    sent = upstream_on.source_calls[0]
    assert sent["source_id"] == "doc-1"
    assert sent["namespace"] == "ai-research"
    assert sent.get("limit") is None


def test_summary_marker_comes_from_the_upstream_column_not_the_heuristic(
        upstream_on, monkeypatch):
    """`chunk_hash == ""` 是摘要行约定。搜索路拿不到这列，浏览路必须拿得到——
    不然 `/data` 的"每组挑一句摘要"会退化成"组内第一条"，且没有任何日志说明
    发生过退化。"""
    monkeypatch.setattr(gateway, "_store", lambda provider=None: _LocalStore())
    row = gateway.browse_all_rows("ai-research")[0]
    assert gateway.is_summary_row(row) is True


# ------------------------------------------------------------------ ② 失败回落

def test_failed_upstream_read_falls_back_loudly_not_silently(upstream_on_failing, monkeypatch,
                                                             caplog):
    local = _LocalStore()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: local)

    with caplog.at_level(logging.WARNING):
        rows = gateway.browse_all_rows("ai-research")
    assert [r["id"] for r in rows] == ["l-1"]
    assert local.all_calls, "读路应回落本地"
    assert any("browse" in r.getMessage() for r in caplog.records), \
        "回落了却没留 warning——静默读到旧库正是最难查的那种"


def test_rows_for_source_falls_back_loudly_too(upstream_on_failing, monkeypatch, caplog):
    local = _LocalStore()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: local)
    with caplog.at_level(logging.WARNING):
        rows = gateway.browse_rows_for_source("ai-research", "doc-1")
    assert [r["id"] for r in rows] == ["l-1"]
    assert any("browse_rows_for_source" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------------ ③ 未配置零变化

def test_unset_env_keeps_browse_exactly_local(upstream_off, monkeypatch):
    local = _LocalStore()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: local)
    assert [r["id"] for r in gateway.browse_all_rows("ai-research")] == ["l-1"]
    assert [r["id"] for r in gateway.browse_rows_for_source("ai-research", "doc-1")] == ["l-1"]
