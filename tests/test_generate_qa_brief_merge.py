"""generate_qa_brief CLI 写回是"对盘上当前内容合并"，不是旧快照覆写。

摘要文件的权威写者是 job_runner 的内联生成；这条 CLI 的生成耗时以十秒计，
拿十秒前的快照整文件回写，会把期间内联更新的字段连灰抹掉（旧行为）。
锁跨不了 LLM 调用——那就把关键操作缩到写前一瞬：重读、补缺、原子落盘。
"""
import json

import src.pipeline.generate_qa_brief as gqb


async def test_writeback_merges_qa_brief_and_keeps_concurrent_updates(tmp_path, monkeypatch):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"item_id": "i1", "qa": {"k1": "有内容"},
                             "qa_brief": {}}), encoding="utf-8")

    async def fake_generate(summary, provider):
        # 模拟生成本身耗时里 job_runner 顺手改了盘：新标题 + 一个它补好的 brief 键
        p.write_text(json.dumps({"item_id": "i1", "title": "改过的标题",
                                 "qa": {"k1": "有内容"},
                                 "qa_brief": {"k1": "内联版"}}), encoding="utf-8")
        return {"k1": "内联版", "k2": "CLI 补的"}

    monkeypatch.setattr(gqb, "generate_brief_for_summary", fake_generate)
    await gqb.process_one(p, "openai")

    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["title"] == "改过的标题", "整文件覆写把并发更新抹掉了"
    assert doc["qa_brief"]["k1"] == "内联版"
    assert doc["qa_brief"]["k2"] == "CLI 补的"


async def test_existing_complete_brief_skips_without_touching_file(tmp_path, monkeypatch):
    p = tmp_path / "y.json"
    p.write_text(json.dumps({"item_id": "y", "qa": {"k1": "a"},
                             "qa_brief": {"k1": "a"}}), encoding="utf-8")
    called = {"gen": False}

    async def fake_generate(*a, **kw):
        called["gen"] = True

    monkeypatch.setattr(gqb, "generate_brief_for_summary", fake_generate)
    await gqb.process_one(p, "openai")
    assert not called["gen"]
