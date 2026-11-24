"""sync_memory_ingest.find_pending_summaries 的"库空了但 flag 还是 True"
漏网场景回归测试——state-auditor 审计实锤的老 bug：memory 库被清空/重建
后，纯 flag 判断让"补灌记忆"一条都不补。

现在 flagged 条目要做一次真实行核对（_existing_ingested_sources），库里
没货就重新入列；库读不到时退回纯 flag 语义，不因为一次库故障把整库重灌。

全程 tmp_path + monkeypatch，不碰真实 queue / memory 库 / LLM。
"""
import json

from src.pipeline import sync_memory_ingest as smi


def _setup(tmp_path, monkeypatch, *, queue, sources, orphan_flag=None):
    """SUMMARIES_DIR 指到 tmp，queue / 库行 / 孤儿标记全部换成注入数据。

    sources=None 表示"库读取失败"——gateway.browse_all_rows 抛异常，
    _existing_ingested_sources 应回退为 None。
    """
    pdf_dir = tmp_path / "summaries" / "pdf"
    pdf_dir.mkdir(parents=True)
    file = pdf_dir / "2601.00001.json"
    payload = {"content": "x"}
    if orphan_flag is not None:
        payload["memory_ingested"] = orphan_flag
    file.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(smi, "SUMMARIES_DIR", tmp_path / "summaries")
    monkeypatch.setattr(smi, "load_queue", lambda: dict(queue))
    if sources is None:
        def boom(namespace=None):
            raise RuntimeError("memory db 不可用")
        monkeypatch.setattr(smi.gateway, "browse_all_rows", boom)
    else:
        rows = [{"source_id": s} for s in sources]
        monkeypatch.setattr(smi.gateway, "browse_all_rows",
                            lambda namespace=None: rows)
    return smi.find_pending_summaries()


def test_flagged_and_row_exists_is_skipped(tmp_path, monkeypatch):
    queue = {"2601.00001": {"pipeline_status": "done",
                            "artifacts": {"memory_ingested": True}}}
    pending = _setup(tmp_path, monkeypatch, queue=queue, sources={"2601.00001"})
    assert pending == []  # 正常已入库：一条都不用补


def test_flagged_but_db_empty_is_rescued(tmp_path, monkeypatch):
    """核心回归：flag=True + 库里没行 = 库被清空/重建，必须重新入列。"""
    queue = {"2601.00001": {"pipeline_status": "done",
                            "artifacts": {"memory_ingested": True}}}
    pending = _setup(tmp_path, monkeypatch, queue=queue, sources=set())
    assert [iid for iid, _ in pending] == ["2601.00001"]


def test_not_flagged_is_pending(tmp_path, monkeypatch):
    queue = {"2601.00001": {"pipeline_status": "done",
                            "artifacts": {"memory_ingested": False}}}
    pending = _setup(tmp_path, monkeypatch, queue=queue, sources=set())
    assert [iid for iid, _ in pending] == ["2601.00001"]


def test_incomplete_item_is_ignored(tmp_path, monkeypatch):
    queue = {"2601.00001": {"pipeline_status": "failed_retryable",
                            "artifacts": {}}}
    pending = _setup(tmp_path, monkeypatch, queue=queue, sources=set())
    assert [iid for iid, _ in pending] == []  # 重管线本身没 done，补灌管不着


def test_orphan_flagged_but_db_empty_is_rescued(tmp_path, monkeypatch):
    """孤儿摘要（queue 里没有条目）自带 memory_ingested=True 时，旧逻辑
    永远跳过——现在同样过库核对。"""
    pending = _setup(tmp_path, monkeypatch, queue={}, sources=set(),
                     orphan_flag=True)
    assert [iid for iid, _ in pending] == ["2601.00001"]


def test_orphan_flagged_and_row_exists_skipped(tmp_path, monkeypatch):
    pending = _setup(tmp_path, monkeypatch, queue={},
                     sources={"2601.00001"}, orphan_flag=True)
    assert pending == []


def test_db_read_failure_falls_back_to_flag_semantics(tmp_path, monkeypatch):
    """库读不到 → 校验不可用，退回纯 flag 判断：flag=True 仍跳过，
    不因为一次故障把整库重灌。"""
    queue = {"2601.00001": {"pipeline_status": "done",
                            "artifacts": {"memory_ingested": True}}}
    pending = _setup(tmp_path, monkeypatch, queue=queue, sources=None)
    assert pending == []  # 保守：宁可不补，不可乱灌
