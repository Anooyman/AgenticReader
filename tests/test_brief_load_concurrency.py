"""轻量入库的卡片并发：N 路同时飞，逐卡语义一字不动。

并发改的是"几张卡在飞"，不该动"每张卡怎么算"——这里分别钉：
  * 并发度受 MEMORY_BRIEF_CONCURRENCY 钳制（默认 3）
  * 每卡仍各自一次 ingest、source_id 各自传
  * 单卡失败不打断整天
  * 全部命中 dedup（chunks_added=0）时仍是 loaded False + skipped True
"""
import asyncio

import src.memory.brief_ingest as bi
import src.memory.upstream as upstream
import src.pipeline.briefs_parser as bp


def _stub_cards(monkeypatch, n):
    def fake_parse(_dir, _date):
        return {"pdf": [{"item_id": f"c{i}", "title": f"纸 {i}"} for i in range(n)],
                "web": []}
    monkeypatch.setattr(bp, "parse_briefs_dir", fake_parse)


def _stub_ingest(monkeypatch, *, boom_ids=(), fail_ids=()):
    state = {"now": 0, "max": 0, "ids": set()}

    async def fake(path, source_type, namespace, source_id):
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        try:
            await asyncio.sleep(0.02)
            state["ids"].add(source_id)
            if source_id in fail_ids:
                return {"available": False, "note": "上游不接这一单"}
            if source_id in boom_ids:
                raise RuntimeError("抽取炸了")
            return {"available": True,
                    "report": {"chunks_added": 1, "chunks_skipped": 0}}
        finally:
            state["now"] -= 1
    monkeypatch.setattr(upstream, "upstream_ingest", fake)
    return state


async def test_concurrency_capped_at_default_three(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMORY_BRIEF_CONCURRENCY", raising=False)
    monkeypatch.setattr(bi, "MEMORY_STAGING_DIR", str(tmp_path))
    _stub_cards(monkeypatch, 9)
    state = _stub_ingest(monkeypatch)
    out = await bi.load_brief_date_upstream("2026-11-25", briefs_dir=tmp_path)
    assert state["max"] <= 3, "并发没被钳制"
    assert state["ids"] == {f"c{i}" for i in range(9)}, "每张卡都该各自一次 ingest"
    assert out["loaded"] and not out["errors"]


async def test_env_override_and_clamp(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_BRIEF_CONCURRENCY", "1")
    assert bi._brief_concurrency() == 1
    monkeypatch.setenv("MEMORY_BRIEF_CONCURRENCY", "99")
    assert bi._brief_concurrency() == 8
    monkeypatch.setenv("MEMORY_BRIEF_CONCURRENCY", "不合法")
    assert bi._brief_concurrency() == 3


async def test_single_card_failure_does_not_stop_the_day(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMORY_BRIEF_CONCURRENCY", raising=False)
    monkeypatch.setattr(bi, "MEMORY_STAGING_DIR", str(tmp_path))
    _stub_cards(monkeypatch, 6)
    _stub_ingest(monkeypatch, boom_ids={"c2"}, fail_ids={"c4"})
    out = await bi.load_brief_date_upstream("2026-11-25", briefs_dir=tmp_path)
    assert out["loaded"] is True
    joined = " ".join(out["errors"])
    assert "c2:" in joined and "c4:" in joined
    assert len(out["errors"]) == 2


async def test_all_dedup_hits_still_reads_skipped(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMORY_BRIEF_CONCURRENCY", raising=False)
    monkeypatch.setattr(bi, "MEMORY_STAGING_DIR", str(tmp_path))
    _stub_cards(monkeypatch, 4)

    async def fake(path, source_type, namespace, source_id):
        return {"available": True,
                "report": {"chunks_added": 0, "chunks_skipped": 3}}

    monkeypatch.setattr(upstream, "upstream_ingest", fake)
    out = await bi.load_brief_date_upstream("2026-11-25", briefs_dir=tmp_path)
    assert out["loaded"] is False and out["skipped"] is True
