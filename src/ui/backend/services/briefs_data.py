"""简报浏览的数据层——解析当天的 briefs HTML，并标注每张卡的处理状态。

改自 ai-research-pipeline 的 webapp/services/briefs_data.py，逻辑原样
保留。解析本身复用 src.pipeline.briefs_parser（与批处理脚本同一实现，
两边算出的 item_id 必须一致，状态比对才准）。这里只做两件事：加状态
标注、把勾选的条目登记进 queue。

**解析不写盘**：浏览一天的简报纯粹是读 HTML，不会往 queue 里塞任何东西。
只有用户明确勾选"加载"的条目才进 queue。
"""
import asyncio
import logging
import os
import re

from src.pipeline.briefs_parser import list_coverage_dates, parse_briefs_dir
from src.pipeline.paths import BRIEFS_DIR, SUMMARIES_DIR
from src.pipeline.queue_store import load_queue, new_queue_item, queue_transaction

logger = logging.getLogger(__name__)

# 卡片状态。not_loaded 之外的都意味着这条已经进过 queue。
STATUS_NOT_LOADED = "not_loaded"      # 还没点过加载
STATUS_QUEUED = "queued"              # 在 queue 里等待/正在处理
STATUS_DONE = "done"                  # 处理完成，有摘要
STATUS_FAILED = "failed"              # 失败（可重试或已熔断）


def date_memory_counts() -> dict:
    """按日期的**真实入库**计数：{date: {"aatf": n, "heavy_done": m}}。

    - aatf：A 自库 AATF namespace 里 occurred_at 落在该日期的行数——
      轻量入库是否真的写过这个库，以行数据为准；
    - heavy_done：queue 里 pipeline_status=done 且 coverage_date 为该日
      期的条目数。
    刻意**不看任务账本**：旧 bridge driver（已退役）时代的
    load_brief_date done 全写在外部 B 侧，A 自库行数为 0——按任务显示会
    把 65 天全标成"已入库"的假状态（审计实锤：23 个 done ↔ 0 行 AATF，
    教训随桥一起留下）。
    AATF 行读取失败只 warning + 跳过，不拖垮整个接口（heavy_done 仍要
    给出）。两处都是小表/字典扫描，不解析 HTML。
    """
    counts = {}
    try:
        from src.memory import gateway  # 函数级 import：UI 服务层不往模块级拖记忆内核
        for row in gateway.browse_all_rows("AATF"):
            day = str(row.get("occurred_at") or "")[:10]
            if day:
                counts.setdefault(day, {"aatf": 0, "heavy_done": 0})["aatf"] += 1
    except Exception:  # noqa: BLE001 - 库缺失/损坏不该让简报页报错
        logger.warning("date_memory_counts: 读取 AATF 行失败，该维度按 0 计", exc_info=True)
    for item in load_queue().values():
        day = str(item.get("coverage_date") or "")
        if day and item.get("pipeline_status") == "done":
            counts.setdefault(day, {"aatf": 0, "heavy_done": 0})["heavy_done"] += 1
    return counts


def available_dates() -> list:
    return list_coverage_dates(BRIEFS_DIR)


def html_dates_presence() -> dict:
    """扫描 BRIEFS_DIR 下各 YYYY-MM-DD 目录实际存在的简报 HTML 文件。

    仅做文件存在性检查（不解析 HTML），供 UI 精确区分：
    - 日历上不存在目录 / 目录里两个 HTML 都没有 → 无简报 HTML
    - 有任一 HTML 但未入库 → 待入库
    """
    result = {}
    for d in list_coverage_dates(BRIEFS_DIR):
        day_dir = BRIEFS_DIR / d
        has_pdf = (day_dir / "research-paper-radar.html").is_file()
        has_web = (day_dir / "daily-signals.html").is_file()
        result[d] = {"has_pdf": has_pdf, "has_web": has_web}
    return result


def queue_stats_by_date() -> dict:
    """按 coverage_date 聚合 pipeline_queue 中重管线各态计数。"""
    stats = {}
    for item in load_queue().values():
        day = str(item.get("coverage_date") or "")
        if not day:
            continue
        bucket = stats.setdefault(day, {"heavy_done": 0, "heavy_queued": 0, "heavy_failed": 0})
        ps = item.get("pipeline_status")
        if ps == "done":
            bucket["heavy_done"] += 1
        elif ps in ("failed_retryable", "failed_permanent"):
            bucket["heavy_failed"] += 1
        else:
            bucket["heavy_queued"] += 1
    return stats


def _build_doc_state_lookup() -> tuple[dict, dict]:
    """一次读取 DocumentRegistry，构造精确名与去版本号基名的索引状态表。

    与 briefs.py:_index_status_of 保持完全同源的判据：
    index_path 存在且磁盘路径存在才算 indexed。
    """
    exact = {}
    siblings = {}
    try:
        from src.core.document_management.registry import DocumentRegistry
        records = DocumentRegistry().list_all()
    except Exception:  # noqa: BLE001 - registry 读取异常不阻断卡片浏览
        logger.warning("briefs_data: 读取 DocumentRegistry 失败，跳过卡片 doc_state 标注", exc_info=True)
        return exact, siblings

    ver_re = re.compile(r"^(.+?)v\d+$", re.IGNORECASE)
    for rec in records:
        name = str(rec.get("doc_name") or "").strip()
        if not name:
            continue
        index_ok = bool(rec.get("index_path")) and os.path.exists(rec["index_path"])
        exact[name] = "indexed" if index_ok else "not_indexed"
        if index_ok:
            m = ver_re.match(name)
            if m:
                siblings.setdefault(m.group(1), name)
    return exact, siblings


def _lookup_doc_state(item_id: str, exact: dict, siblings: dict) -> dict:
    if item_id in exact:
        return {"state": exact[item_id], "doc_name": item_id}
    if item_id in siblings:
        return {"state": "indexed_elsewhere", "doc_name": siblings[item_id]}
    return {"state": "none", "doc_name": ""}


def _local_memory_source_ids(namespace: str) -> set:
    try:
        from src.memory import gateway
        return {
            str(r.get("source_id") or "")
            for r in gateway.browse_all_rows(namespace)
            if r.get("source_id")
        }
    except Exception:  # noqa: BLE001
        return set()


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


def load_cards(coverage_date: str, include_state: bool = False, compact: bool = False) -> dict:
    """解析某一天的简报，每张卡带上处理状态。纯读，不改任何状态。

    - include_state=True：额外标注单卡在本地 PDF 文档库的状态（doc_state）
      以及本地记忆库命中标记（in_aatf / in_ai_research）。
    - compact=True：省略前端不展示的英文长字段（english_brief/why/excerpt），
      显著减小大日期响应体积。
    """
    parsed = parse_briefs_dir(BRIEFS_DIR, coverage_date)
    queue = load_queue()

    exact_docs, sibling_docs = ({}, {})
    aatf_sources, ai_research_sources = (set(), set())
    if include_state:
        exact_docs, sibling_docs = _build_doc_state_lookup()
        aatf_sources = _local_memory_source_ids("AATF")
        ai_research_sources = _local_memory_source_ids("ai-research")

    for kind in ("pdf", "web"):
        for card in parsed[kind]:
            card.update(_card_status(card["item_id"], card["type"], queue))
            if include_state:
                iid = card["item_id"]
                card["in_aatf"] = iid in aatf_sources
                card["in_ai_research"] = (card["status"] == STATUS_DONE) or (iid in ai_research_sources)
                if kind == "pdf":
                    card["doc_state"] = _lookup_doc_state(iid, exact_docs, sibling_docs)
            if compact:
                card.pop("english_brief", None)
                card.pop("why", None)
                card.pop("excerpt", None)

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
