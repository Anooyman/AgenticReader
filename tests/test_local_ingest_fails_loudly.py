"""本地 ingest 的部分失败必须响，不许装成成功。

`ingest.ingest_source` 把逐 chunk 的 condense/embed 失败记进 `chunks_failed`
后照常 return——三个调用方（chat_ingest 水位线 / common 的 memory_ingested /
sync_memory_ingest 补灌账）都按"没抛即成功"记账，端点抖动时一次真实失败会被
记成"已入库"，水位线一推这会话的记忆就再没人回来补。gateway 在本地路加了
与上游路对称的 raise；这条钉住它。
"""
import pytest

from src.memory import gateway


@pytest.fixture()
def local_route(monkeypatch):
    async def no_route(where):
        return False
    monkeypatch.setattr(gateway, "_route_is_upstream", no_route)
    monkeypatch.setattr(gateway, "resolve_provider", lambda p=None: "openai")


async def test_local_ingest_raises_when_chunks_failed_nonempty(local_route, monkeypatch):
    async def fake_source(path, source_type, namespace, provider, source_id=None):
        return {"chunks_added": 1, "chunks_skipped": 0, "chunks_deleted": 0,
                "chunks_failed": [{"chunk_hash": "abc", "error": "embed 401"}]}

    monkeypatch.setattr(gateway, "_ingest_source", fake_source)
    with pytest.raises(RuntimeError) as exc:
        await gateway.ingest("/tmp/whatever.json", "ai_research", "ai-research")
    assert "chunks_failed" in str(exc.value) or "未写入" in str(exc.value)


async def test_local_ingest_full_failure_raises(local_route, monkeypatch):
    async def fake_source(path, source_type, namespace, provider, source_id=None):
        return {"chunks_added": 0, "chunks_skipped": 0, "chunks_deleted": 0,
                "chunks_failed": [{"chunk_hash": "h", "error": "llm timeout"}]}

    monkeypatch.setattr(gateway, "_ingest_source", fake_source)
    with pytest.raises(RuntimeError):
        await gateway.ingest("/tmp/whatever.json", "ai_research", "ai-research")


async def test_local_ingest_success_returned_intact(local_route, monkeypatch):
    """没有失败时形状逐字不变——三个调用方都读这几个键。"""
    async def fake_source(path, source_type, namespace, provider, source_id=None):
        return {"chunks_added": 2, "chunks_skipped": 1, "chunks_deleted": 0}

    monkeypatch.setattr(gateway, "_ingest_source", fake_source)
    report = await gateway.ingest("/tmp/whatever.json", "ai_research", "ai-research")
    assert report["chunks_added"] == 2
