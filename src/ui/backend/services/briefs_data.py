"""简报浏览的数据层——解析当天的 briefs HTML，并标注每张卡的处理状态。

改自 ai-research-pipeline 的 webapp/services/briefs_data.py，逻辑原样
保留。解析本身复用 src.pipeline.briefs_parser（与批处理脚本同一实现，
两边算出的 item_id 必须一致，状态比对才准）。这里只做两件事：加状态
标注、把勾选的条目登记进 queue。

**解析不写盘**：浏览一天的简报纯粹是读 HTML，不会往 queue 里塞任何东西。
只有用户明确勾选"加载"的条目才进 queue。
"""
import asyncio

from src.pipeline.briefs_parser import list_coverage_dates, parse_briefs_dir
from src.pipeline.paths import BRIEFS_DIR, SUMMARIES_DIR
from src.pipeline.queue_store import load_queue, new_queue_item, queue_transaction

# 卡片状态。not_loaded 之外的都意味着这条已经进过 queue。
STATUS_NOT_LOADED = "not_loaded"      # 还没点过加载
STATUS_QUEUED = "queued"              # 在 queue 里等待/正在处理
STATUS_DONE = "done"                  # 处理完成，有摘要
STATUS_FAILED = "failed"              # 失败（可重试或已熔断）


def available_dates() -> list:
    return list_coverage_dates(BRIEFS_DIR)


def _summary_exists(item_id: str, item_type: str) -> bool:
    subdir = "pdf" if item_type == "pdf_arxiv" else "web"
    return (SUMMARIES_DIR / subdir / f"{item_id}.json").exists()


def _card_status(item_id: str, item_type: str, queue: dict) -> dict:
    item = queue.get(item_id)
    if item is None:
        # queue 里没有，但摘要文件在——历史遗留（条目被清理过但产出还在），
        # 仍然算已完成，不该让用户重复处理一遍。
        if _summary_exists(item_id, item_type):
            return {"status": STATUS_DONE, "pipeline_status": None, "attempts": 0}
        return {"status": STATUS_NOT_LOADED, "pipeline_status": None, "attempts": 0}

    pipeline_status = item.get("pipeline_status")
    if pipeline_status == "done":
        status = STATUS_DONE
    elif pipeline_status in ("failed_retryable", "failed_permanent"):
        status = STATUS_FAILED
    else:  # pending / in_progress
        status = STATUS_QUEUED
    return {
        "status": status,
        "pipeline_status": pipeline_status,
        "attempts": item.get("attempts", 0),
        "last_error": item.get("last_error"),
    }


def load_cards(coverage_date: str) -> dict:
    """解析某一天的简报，每张卡带上处理状态。纯读，不改任何状态。"""
    parsed = parse_briefs_dir(BRIEFS_DIR, coverage_date)
    queue = load_queue()

    for kind in ("pdf", "web"):
        for card in parsed[kind]:
            card.update(_card_status(card["item_id"], card["type"], queue))

    counts = {}
    for kind in ("pdf", "web"):
        for card in parsed[kind]:
            counts[card["status"]] = counts.get(card["status"], 0) + 1

    return {
        "coverage_date": coverage_date,
        "pdf": parsed["pdf"],
        "web": parsed["web"],
        "counts": counts,
    }


def _register(coverage_date: str, item_ids: list) -> list:
    """短事务：把选中的卡片登记进 queue，返回真正需要跑任务的条目。

    已经 done 的直接跳过（不重复处理）；已在 queue 里但没跑完的（pending /
    失败重试）不新建条目，但仍然返回去排任务，这样"重试失败的那条"也能从
    页面上点。"""
    parsed = parse_briefs_dir(BRIEFS_DIR, coverage_date)
    by_id = {c["item_id"]: c for c in parsed["pdf"] + parsed["web"]}

    to_run = []
    with queue_transaction() as queue:
        for item_id in item_ids:
            card = by_id.get(item_id)
            if card is None:
                continue  # 不是这一天的卡，忽略
            existing = queue.get(item_id)
            if existing is None:
                queue[item_id] = new_queue_item(
                    item_id=card["item_id"], item_type=card["type"], url=card["url"],
                    title=card["title"], coverage_date=card["coverage_date"],
                    pdf_url=card.get("pdf_url"),
                )
            elif existing.get("pipeline_status") == "done":
                continue
            to_run.append({"item_id": item_id, "type": card["type"], "title": card["title"]})
    return to_run


async def register_for_processing(coverage_date: str, item_ids: list) -> list:
    """queue_transaction 里的 flock 是阻塞调用，不能在事件循环里直接跑。"""
    return await asyncio.to_thread(_register, coverage_date, item_ids)
