"""search 的两层兜底：轮数旋钮（upstream.py）与行扫描（gateway.py）。

钉 2026-11-26 的"24号查不到"事故：上游 6 轮 agentic search 实测 133s，
AR 的 90s 硬 cap 每次都把注定成功的检索掐死，然后按读路回落到**空的**本地
旧库（AATF 在上游，本地 0 行）——chat 于是永远"没找到"，报错还不响。
两层各钉各的：
  ① 轮数/时限 env 旋钮必须真的传进 client.search 的入参（缺省 3 轮）；
  ② search 未成时先扫上游真行：日期命中给高分，纯虚词零命中不兜底，
     browse 面也不通才落本地——兜底的形状必须逐字等于 agentic_search。
"""
import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.memory import gateway, upstream  # noqa: E402

ROW_24 = {
    "id": "r-24", "namespace": "AATF", "memory_type": "observation",
    "abstract": "On 2026-11-24, a brief was ingested for the paper "
                "\"Federated Policy Gradient\" (arXiv 2611.28777).",
    "detail": "x" * 100, "keywords": ["paper", "2026-11-24"],
    "created_at": "2026-11-25T17:30:00", "occurred_at": "2026-11-24T00:00:00",
    "source_type": "brief", "source_id": "2611.28777",
    "chunk_hash": "abc", "raw_source": "data.json", "importance": 0.7,
}
ROW_OLD = {**ROW_24, "id": "r-old", "occurred_at": "2026-10-01T00:00:00",
           "abstract": "a paper about gardening", "keywords": [], "detail": "",
           "source_id": "9000.00001"}


@pytest.fixture
def upstream_search_down(monkeypatch):
    """上游 search 面"不通"、browse 面正常——就是 2026-11-26 的事故现场。"""
    async def _dead(*a, **k):
        return {"available": False, "error": "TimeoutError",
                "note": "上游 search 超 150s 未回"}
    monkeypatch.setattr(upstream, "upstream_search", _dead)
    monkeypatch.setattr(upstream, "upstream_browse_all_rows",
                        lambda *a, **k: {"available": True,
                                         "rows": [ROW_OLD, ROW_24]})
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    # 强制走上游路（跳过 _client 探测）
    async def _yes(*a, **k):
        return True
    monkeypatch.setattr(gateway, "_route_is_upstream", _yes)
    return monkeypatch


def test_rowscan_picks_date_matching_row(upstream_search_down):
    result = asyncio.run(gateway.search("24号有什么新颖的 paper 和新闻",
                                        namespaces=["AATF"]))
    ids = [r["id"] for r in result["results"]]
    assert "r-24" in ids, "24 号那行必须被扫出来"
    assert result["results"][0]["id"] == "r-24", "日期命中要排第一"
    # 形状契约：和 agentic_search 四键逐字同，不许多键
    assert set(result) == {"answer", "results", "iterations", "tool_calls_made"}
    assert set(result["results"][0]) <= {
        "id", "namespace", "memory_type", "abstract", "detail", "keywords",
        "created_at", "occurred_at", "source_type", "source_id",
        "chunk_hash", "raw_source", "importance", "score"}


def test_no_match_falls_back_to_local(upstream_search_down, monkeypatch):
    monkeypatch.setattr(upstream, "upstream_browse_all_rows",
                        lambda *a, **k: {"available": True, "rows": [ROW_OLD]})
    sentinel = {"answer": "local", "results": [], "iterations": 1, "tool_calls_made": 1}
    async def _fake_local(query, namespace=None, provider=None, max_iterations=None):
        return sentinel
    monkeypatch.setattr(gateway, "_agentic_search", _fake_local)
    result = asyncio.run(gateway.search("zzqxyz 完全不相干的内容", namespaces=["AATF"]))
    assert result is sentinel, "行扫描零命中时要照常落本地旧路"


def test_browse_dead_also_falls_to_local(upstream_search_down, monkeypatch):
    monkeypatch.setattr(upstream, "upstream_browse_all_rows",
                        lambda *a, **k: {"available": False, "note": "browse 也不通"})
    sentinel = {"answer": "local", "results": [], "iterations": 1, "tool_calls_made": 1}
    async def _fake_local(query, namespace=None, provider=None, max_iterations=None):
        return sentinel
    monkeypatch.setattr(gateway, "_agentic_search", _fake_local)
    result = asyncio.run(gateway.search("24号 有什么", namespaces=["AATF"]))
    assert result is sentinel


def test_search_round_knobs_reach_client(monkeypatch):
    captured = {}

    class FakeClient:
        def search(self, query, **kw):
            captured.update(kw)
            return {"results": [], "answer": "", "iterations": 1, "tool_calls_made": 1}

    fake = FakeClient()
    # 让 _client_for 直接给出假 client，不碰真实寻址
    async def _for():
        return fake, None
    monkeypatch.setattr(upstream, "_client_for", _for)
    monkeypatch.delenv("MEMORY_SEARCH_MAX_ROUNDS", raising=False)
    asyncio.run(upstream.upstream_search("q", namespace="AATF"))
    assert captured.get("max_iterations") == 3, "缺省必须压到 3 轮"

    monkeypatch.setenv("MEMORY_SEARCH_MAX_ROUNDS", "5")
    captured.clear()
    asyncio.run(upstream.upstream_search("q", namespace="AATF"))
    assert captured.get("max_iterations") == 5
    monkeypatch.setenv("MEMORY_SEARCH_MAX_ROUNDS", "99")
    captured.clear()
    asyncio.run(upstream.upstream_search("q", namespace="AATF"))
    assert captured.get("max_iterations") == 8, "上限钳到 8"
