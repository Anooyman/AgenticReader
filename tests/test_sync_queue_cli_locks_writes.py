"""sync_pipeline_queue 的写回必须走 queue_transaction——CLI 侧的锁外裸写曾是全仓
唯一的 lost-update 入口：load→改→save 一个整文件快照，与 job_runner 的
claim/finish 并发时把对方的状态推进整体抹掉。这里钉它确实持锁读写、
且不覆盖已有条目状态。
"""
import json

import pytest

from src.pipeline import queue_store, sync_pipeline_queue


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(queue_store, "QUEUE_PATH", tmp_path / "pipeline_queue.json")
    monkeypatch.setattr(queue_store, "QUEUE_LOCK_PATH", tmp_path / "pipeline_queue.lock")
    return tmp_path


def _fake_cards(monkeypatch):
    monkeypatch.setattr(sync_pipeline_queue, "parse_paper_cards", lambda d, c: [
        {"item_id": "pdf-1", "type": "pdf_arxiv", "url": "u", "title": "t1",
         "coverage_date": c, "pdf_url": "p"}])
    monkeypatch.setattr(sync_pipeline_queue, "parse_signal_cards", lambda d, c: [
        {"item_id": "web-1", "type": "web_article", "url": "u", "title": "t2",
         "coverage_date": c}])


async def test_cli_writes_through_the_transaction(sandbox, monkeypatch):
    _fake_cards(monkeypatch)
    held = []
    orig = queue_store.queue_transaction

    class _Spy:
        def __enter__(self):
            held.append("enter")
            self._cm = orig()
            return self._cm.__enter__()

        def __exit__(self, *a):
            r = self._cm.__exit__(*a)
            held.append("exit")
            return r

    # 不用 with queue_transaction as q 的入口会漏锁——只要它真走事务，
    # enter/exit 各来一次，且落盘在这对括号之间
    monkeypatch.setattr(sync_pipeline_queue, "queue_transaction",
                        lambda: _Spy())
    import sys
    monkeypatch.setattr(sys, "argv",
                        ["prog", "--coverage-date", "2026-11-01"])
    sync_pipeline_queue.main()

    assert held == ["enter", "exit"], "没有经过 queue_transaction 的锁段"
    q = json.loads((sandbox / "pipeline_queue.json").read_text(encoding="utf-8"))
    assert q["pdf-1"]["pipeline_status"] == "pending"
    assert q["web-1"]["type"] == "web_article"
