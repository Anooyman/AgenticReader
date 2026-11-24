"""brief_ingest.load_brief_date_local 的纯逻辑测试——轻量写入 A 自库 AATF
的三种路径：全新写入 / 幂等跳过 / 内容变更后替换。

不碰 LanceDB 与 embedding 服务：VectorStore、LLMBase、parser 全部换成
内存假件，只核对本模块自己写下的契约（字段形状、skip/replace 判定、
单卡失败隔离）。
"""
import asyncio
import hashlib

from src.memory import brief_ingest


def _card(item_id, *, title="标题", cn=None, themes=None, url=None):
    return {
        "item_id": item_id, "type": "pdf_arxiv", "title": title,
        "url": url or f"https://arxiv.org/abs/{item_id}",
        "pdf_url": None, "score": "", "coverage_date": "2026-11-13",
        "themes": themes or ["AI Agents"],
        "cn": cn if cn is not None else {"导读": "这是一段中文导读。"},
    }


class FakeStore:
    """记录 add/delete 的 VectorStore 替身；seed 提供"库里已有什么"。
    ops 与 FakeEmbed 共享，用来钉死操作顺序（embed 必须先于 delete/add）。"""

    def __init__(self, seed=None, ops=None):
        self.added = []
        self.deleted = []
        self._seed = seed or {}  # source_id -> [rows]
        self.ops = ops if ops is not None else []

    def rows_for_source(self, namespace, source_id):
        assert namespace == "AATF"
        return list(self._seed.get(source_id, []))

    def add(self, record):
        self.added.append(record)
        self.ops.append("add")
        return record

    def delete(self, row_id):
        self.deleted.append(row_id)
        self.ops.append("delete")


class FakeEmbed:
    def __init__(self, fail_on=None, ops=None):
        self.fail_on = set(fail_on or ())
        self.queries = []
        self.ops = ops if ops is not None else []

    async def aembed_query(self, text):
        for key in self.fail_on:
            if key in text:
                raise RuntimeError("embedding 服务 401")
        self.queries.append(text)
        self.ops.append("embed")
        return [0.1] * 1536


def _run(monkeypatch, cards, *, seed=None, fail_on=()):
    """跑一次 load_brief_date_local，返回 (outcome, store, embed)。"""
    ops = []
    store = FakeStore(seed=seed, ops=ops)
    embed = FakeEmbed(fail_on=fail_on, ops=ops)

    monkeypatch.setattr(brief_ingest, "VectorStore", lambda path, dims: store)
    monkeypatch.setattr(brief_ingest, "resolve_provider", lambda p=None: "openai")
    monkeypatch.setattr(brief_ingest, "get_embedding_dimensions", lambda p: 1536)

    class FakeLLM:
        def __init__(self, provider=None):
            self.embedding_model = embed

    import src.core.llm as core_llm
    monkeypatch.setattr(core_llm, "LLMBase", FakeLLM)

    import src.pipeline.briefs_parser as parser
    monkeypatch.setattr(parser, "parse_briefs_dir",
                        lambda d, date: {"pdf": list(cards.get("pdf", [])),
                                         "web": list(cards.get("web", []))})
    import src.pipeline.paths as paths
    monkeypatch.setattr(paths, "BRIEFS_DIR", "/nonexistent")

    outcome = asyncio.run(brief_ingest.load_brief_date_local("2026-11-13"))
    return outcome, store, embed


def test_fresh_write_shape(monkeypatch):
    cards = {"pdf": [_card("2601.00001", cn={"导读": "第一篇"}),
                     _card("2601.00002", cn={"导读": "第二篇"}, themes=["RAG"])]}
    outcome, store, embed = _run(monkeypatch, cards)

    assert outcome == {"loaded": True, "skipped": False, "errors": []}
    assert len(store.added) == 2 and not store.deleted
    r1 = store.added[0]
    assert r1["namespace"] == "AATF"
    assert r1["source_id"] == "2601.00001"
    assert r1["source_type"] == "brief"
    assert r1["memory_type"] == "episodic"
    assert "第一篇" in r1["detail"] and "2601.00001" in r1["raw_source"]
    assert r1["chunk_hash"] == hashlib.sha256(store.added[0]["detail"].encode()).hexdigest()[:16]
    assert r1["keywords"] == '["AI Agents"]'
    assert r1["occurred_at"].startswith("2026-11-13")
    assert r1["vector"] == [0.1] * 1536
    assert len(embed.queries) == 2


def test_idempotent_skip(monkeypatch):
    card = _card("2601.00001")
    # 预置一条 chunk_hash 与当前内容完全一致的旧行 → 不应再写任何东西
    text_hash = hashlib.sha256(brief_ingest._card_text(card).encode()).hexdigest()[:16]
    seed = {"2601.00001": [{"id": "old-1", "chunk_hash": text_hash}]}
    outcome, store, embed = _run(monkeypatch, {"pdf": [card]}, seed=seed)

    assert outcome == {"loaded": False, "skipped": True, "errors": []}
    assert store.added == [] and store.deleted == [] and embed.queries == []


def test_stale_row_replaced(monkeypatch):
    card = _card("2601.00001")
    seed = {"2601.00001": [{"id": "old-1", "chunk_hash": "ffffffffffffffff"}]}
    outcome, store, _ = _run(monkeypatch, {"pdf": [card]}, seed=seed)

    assert outcome["loaded"] is True
    assert store.deleted == ["old-1"]
    assert len(store.added) == 1
    assert store.added[0]["chunk_hash"] != "ffffffffffffffff"
    # 钉死顺序：embed 必须先于 delete——若先删后 embed，embedding 一失败
    # 这个 source 的既有条目就凭空蒸发（reviewer 发现的破坏性时序）。
    assert store.ops == ["embed", "delete", "add"]


def test_per_card_failure_isolated(monkeypatch):
    cards = {"pdf": [_card("bad1.00001", cn={"导读": "坏卡"}),
                     _card("good.00002", cn={"导读": "好卡"}),
                     _card("bad2.00003", cn={"导读": "坏卡2"})],
             "web": [_card("web-1", url="https://example.com/a", cn={"导读": "网页导读"})]}
    # fail_on 按 item_id 出现在卡片文本里——两处命中即两个 source 报错，
    # 其余照常写入
    outcome, store, _ = _run(monkeypatch, cards, fail_on=("bad1.00001", "bad2.00003"))

    assert outcome["loaded"] is True
    assert len(outcome["errors"]) == 2
    assert any("bad1.00001" in e for e in outcome["errors"])
    assert len(store.added) == 2  # good.00002 + web-1


def test_empty_day_is_skipped_not_failed(monkeypatch):
    outcome, store, embed = _run(monkeypatch, {"pdf": [], "web": []})
    assert outcome == {"loaded": False, "skipped": True, "errors": []}
    assert store.added == [] and embed.queries == []
