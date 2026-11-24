"""Phase 2 /briefs API 与解析去重增强回归测试。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.pipeline.briefs_parser import parse_paper_cards
from src.ui.backend.api.v1 import briefs
from src.ui.backend.services import briefs_data


def _make_client():
    app = FastAPI()
    app.include_router(briefs.router, prefix="/api/v1/briefs")
    return TestClient(app)


def test_parse_paper_cards_deduplicates_by_item_id(tmp_path):
    html = """
    <article class="paper">
      <h3>Paper A (v1)</h3>
      <div class="score">Discovery 80.2 arXiv</div>
      <a href="https://arxiv.org/abs/2607.11185v1">abs</a>
      <a href="https://arxiv.org/pdf/2607.11185v1">pdf</a>
    </article>
    <article class="paper">
      <h3>Paper A Duplicate (v2)</h3>
      <div class="score">Discovery 75.2 arXiv</div>
      <a href="https://arxiv.org/abs/2607.11185v2">abs</a>
    </article>
    <article class="paper">
      <h3>Paper B</h3>
      <a href="https://arxiv.org/abs/2607.22222">abs</a>
    </article>
    """
    p = tmp_path / "research-paper-radar.html"
    p.write_text(html, encoding="utf-8")

    items = parse_paper_cards(p, "2026-11-21")
    assert [i["item_id"] for i in items] == ["2607.11185", "2607.22222"]
    assert items[0]["title"] == "Paper A (v1)"


def test_memory_status_include_meta_opt_in(monkeypatch):
    client = _make_client()
    monkeypatch.setattr(briefs_data, "date_memory_counts",
                        lambda: {"2026-11-21": {"aatf": 0, "heavy_done": 1}})
    monkeypatch.setattr(briefs_data, "html_dates_presence",
                        lambda: {"2026-11-21": {"has_pdf": True, "has_web": True}})
    monkeypatch.setattr(briefs_data, "queue_stats_by_date",
                        lambda: {"2026-11-21": {"heavy_done": 1, "heavy_queued": 2, "heavy_failed": 0}})

    # 默认不传 include_meta 时，保持严格向后兼容（仅 dates 单键）
    r_plain = client.get("/api/v1/briefs/memory-status")
    assert r_plain.status_code == 200
    assert r_plain.json() == {"dates": {"2026-11-21": {"aatf": 0, "heavy_done": 1}}}

    # 传 include_meta=1 时透出 meta
    r_meta = client.get("/api/v1/briefs/memory-status?include_meta=1")
    assert r_meta.status_code == 200
    body = r_meta.json()
    assert body["dates"] == {"2026-11-21": {"aatf": 0, "heavy_done": 1}}
    assert body["meta"]["storage_mode"] in ("local", "upstream")
    assert body["meta"]["html_dates"] == {"2026-11-21": {"has_pdf": True, "has_web": True}}
    assert body["meta"]["queue_by_date"]["2026-11-21"]["heavy_queued"] == 2


def test_cards_include_state_and_compact(monkeypatch):
    client = _make_client()

    fake_parsed = {
        "pdf": [{
            "item_id": "2607.11185",
            "type": "pdf_arxiv",
            "title": "Test Paper",
            "url": "https://arxiv.org/abs/2607.11185",
            "pdf_url": "https://arxiv.org/pdf/2607.11185",
            "coverage_date": "2026-11-21",
            "score": "Discovery 80.2 arXiv",
            "authors": "",
            "themes": [],
            "english_brief": "Long English brief...",
            "cn": {},
            "why": "Boilerplate why...",
        }],
        "web": [{
            "item_id": "abcd1234",
            "type": "web_article",
            "title": "Test Article",
            "url": "https://example.com/a",
            "coverage_date": "2026-11-21",
            "topic_tag": "AI",
            "cn": {"中文导读": "测试导读"},
            "excerpt": "Long excerpt...",
            "followup": "",
        }],
    }
    monkeypatch.setattr(briefs_data, "parse_briefs_dir",
                        lambda *_a, **_kw: {
                            "pdf": [dict(fake_parsed["pdf"][0])],
                            "web": [dict(fake_parsed["web"][0])],
                        })
    monkeypatch.setattr(briefs_data, "load_queue", lambda: {})
    monkeypatch.setattr(briefs_data, "_summary_exists", lambda *_a: False)
    monkeypatch.setattr(briefs_data, "_build_doc_state_lookup",
                        lambda: ({}, {"2607.11185": "2607.11185v1"}))
    monkeypatch.setattr(briefs_data, "_local_memory_source_ids",
                        lambda ns: {"2607.11185"} if ns == "AATF" else set())

    r = client.get("/api/v1/briefs/cards?coverage_date=2026-11-21&include_state=1&compact=1")
    assert r.status_code == 200
    body = r.json()
    p = body["pdf"][0]
    w = body["web"][0]
    assert p["doc_state"] == {"state": "indexed_elsewhere", "doc_name": "2607.11185v1"}
    assert p["in_aatf"] is True
    assert p["in_ai_research"] is False
    assert "english_brief" not in p
    assert "why" not in p
    assert "excerpt" not in w
