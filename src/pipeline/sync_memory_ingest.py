"""把 data/pipeline/summaries/{pdf,web}/*.json 里已完成(pipeline_status=done)
但尚未写入 memory 的摘要，逐个通过 src.memory.ingest 写入 namespace
"ai-research"。

改自 ai-research-pipeline 的 pipeline/sync_memory_ingest.py。原实现走
subprocess 调用 LLM-Memory 的 ingest.py CLI（因为两个仓库 venv 隔离，只能
"调用+读取结果"）；合并进 AgenticReader 后 src.memory.ingest 与本项目其余
代码在同一进程里，直接 import 调用即可。

正常路径下 process_pdf_queue.py/process_web_queue.py 处理完一篇就已经
调用过一次 ingest_source（见两者的 process_item）——本脚本存在的意义是
补历史欠账：(a) memory 库被清空/重建过；(b) 早期处理的条目当时那次 inline
ingest 失败了（memory_ingested=False）；(c) 手动测试产生的"孤儿"摘要
（queue 里没有对应条目）。

用法：
    python3 -m src.pipeline.sync_memory_ingest [--limit N]
"""
import argparse
import asyncio
import json

from src.memory.config import NAMESPACE_AI_RESEARCH
from src.memory.ingest import ingest_source
from src.pipeline.paths import SUMMARIES_DIR, write_json_atomic
from src.pipeline.queue_store import load_queue, queue_transaction


def _orphan_already_ingested(summary_path) -> bool:
    """queue 里没有条目的"孤儿"摘要，其 ingest 标记记录在摘要 JSON 自身的
    顶层 memory_ingested 字段里。"""
    try:
        with open(summary_path, encoding="utf-8") as f:
            return bool(json.load(f).get("memory_ingested"))
    except (json.JSONDecodeError, OSError):
        return False


def find_pending_summaries(only_item_id: str = None) -> list:
    """扫描 summaries/{pdf,web}/*.json，找出尚未写入 memory 的摘要：queue
    里有条目的看 artifacts.memory_ingested，孤儿文件看其自身的
    memory_ingested 字段。"""
    queue = load_queue()
    pending = []
    for subdir in ("pdf", "web"):
        d = SUMMARIES_DIR / subdir
        if not d.exists():
            continue
        for summary_path in sorted(d.glob("*.json")):
            item_id = summary_path.stem
            if only_item_id is not None and item_id != only_item_id:
                continue
            item = queue.get(item_id)
            if item is None:
                if not _orphan_already_ingested(summary_path):
                    pending.append((item_id, summary_path))
                continue
            if item.get("pipeline_status") != "done":
                continue
            if item.get("artifacts", {}).get("memory_ingested"):
                continue
            pending.append((item_id, summary_path))
    return pending


def mark_memory_ingested(item_id: str) -> bool:
    """短事务：给 queue 里的条目打上已入库标记。返回 False 表示 queue 里
    没有这个条目（孤儿摘要），调用方改为把标记写进摘要文件自身。"""
    with queue_transaction() as queue:
        item = queue.get(item_id)
        if item is None:
            return False
        item.setdefault("artifacts", {})["memory_ingested"] = True
        return True


async def main_async(limit: int, provider: str, item_id: str = None):
    pending = find_pending_summaries(only_item_id=item_id)
    if limit:
        pending = pending[:limit]

    print(f"待写入 memory 的摘要数: {len(pending)}")

    done_count, failed_count = 0, 0
    for iid, summary_path in pending:
        print(f"\n=== ingest {iid}: {summary_path.name} ===")
        try:
            report = await ingest_source(
                str(summary_path), source_type="ai_research",
                namespace=NAMESPACE_AI_RESEARCH, provider=provider, source_id=iid,
            )
            print(f"  ✅ 成功: +{report.get('chunks_added')} chunks（跳过 {report.get('chunks_skipped')}）")
            if not mark_memory_ingested(iid):
                with open(summary_path, encoding="utf-8") as f:
                    summary = json.load(f)
                summary["memory_ingested"] = True
                write_json_atomic(summary_path, summary)
            done_count += 1
        except Exception as e:
            print(f"  ❌ 失败: {e}")
            failed_count += 1

    print(f"\n汇总: 成功 {done_count} / 失败 {failed_count} / 共处理 {len(pending)} 条")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--item-id", default=None,
                        help="只入库这一条（webapp 处理完单篇后紧接着调用）")
    parser.add_argument("--provider", default="openai")
    args = parser.parse_args()
    asyncio.run(main_async(args.limit, args.provider, args.item_id))


if __name__ == "__main__":
    main()
