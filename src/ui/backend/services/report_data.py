"""Report 数据读取 + 条目删除——合并自 ai-research-pipeline 的
webapp/report_data.py 和 webapp/services/item_delete.py。

## 数据读取
复用 render_report.py 已验证过的 load_summaries 逻辑，供 REST API 和模板
共用（webapp 场景是"在线 API"而不是"离线生成静态文件"）。

## 条目删除
一篇内容处理完之后同时存在于三处：
    summary  data/pipeline/summaries/{pdf,web}/{item_id}.json → /report 页显示的就是它
    queue    data/pipeline/pipeline_queue.json 里的条目        → 简报页的"已完成"徽标
    memory   src.memory 的 ai-research namespace              → search_memory 能否检索到
    index    AgenticReader 的索引/PDF/图片                     → deep_dive_document 能否深挖

原实现里 memory/index 两项要 subprocess 调用两个兄弟仓库各自的 worker
脚本（因为当时三者分属不同 venv）；合并进 AgenticReader 后 memory/index
删除都是本项目内部的直接函数调用（src.memory.vector_store.VectorStore /
src.core.document_management.DocumentRegistry），不再需要 subprocess。

四项独立可选（UI 上勾选）：删掉展示但保留索引和记忆是合理需求（"列表里
不想看到，但数据别丢"），所以不强制全删。每一项独立 try/except——memory
或 index 删失败不该导致 summary 也留下，那反而制造出新的不一致。
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from src.memory.config import MEMORY_DB_DIR, NAMESPACE_AI_RESEARCH, get_embedding_dimensions
from src.pipeline.paths import SUMMARIES_DIR
from src.pipeline.qa_labels import QA_LABELS  # noqa: F401  （re-export，供 pages.py 等取用）
from src.pipeline.queue_store import queue_transaction

logger = logging.getLogger(__name__)

VALID_DELETE_TARGETS = ("summary", "queue", "memory", "index")


# ==================== 数据读取 ====================

def load_summaries(subdir: str) -> list:
    d = SUMMARIES_DIR / subdir
    if not d.exists():
        return []
    summaries = []
    for path in sorted(d.glob("*.json"), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                summaries.append(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("跳过无法解析的摘要文件 %s: %s", path, e)
    return summaries


def load_all_summaries(coverage_date: Optional[str] = None) -> dict:
    """coverage_date 为 None 时返回全部；传具体日期时只返回该日期的条目
    ——用于 report 页面默认只看"今天"，避免随着每日新增内容，列表越来越
    长、一次性全量渲染越来越慢。"""
    pdf = load_summaries("pdf")
    web = load_summaries("web")
    if coverage_date:
        pdf = [s for s in pdf if s.get("coverage_date") == coverage_date]
        web = [s for s in web if s.get("coverage_date") == coverage_date]
    return {"pdf": pdf, "web": web}


def list_coverage_dates() -> list:
    """返回所有出现过的 coverage_date，去重降序排列。"""
    dates = set()
    for subdir in ("pdf", "web"):
        for s in load_summaries(subdir):
            d = s.get("coverage_date")
            if d:
                dates.add(d)
    return sorted(dates, reverse=True)


def load_summary_by_item_id(item_id: str) -> dict:
    for subdir in ("pdf", "web"):
        path = SUMMARIES_DIR / subdir / f"{item_id}.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return {}


# ==================== 条目删除 ====================

def _summary_path(item_id: str) -> Optional[Path]:
    for subdir in ("pdf", "web"):
        path = SUMMARIES_DIR / subdir / f"{item_id}.json"
        if path.exists():
            return path
    return None


def describe_delete_targets(item_id: str) -> dict:
    """告诉前端这个条目当前在哪几处有东西，好让确认框只列出真实存在的。"""
    summary_path = _summary_path(item_id)
    doc_name = None
    if summary_path:
        try:
            with open(summary_path, encoding="utf-8") as f:
                doc_name = json.load(f).get("doc_name")
        except (json.JSONDecodeError, OSError):
            pass

    with queue_transaction() as queue:
        item = queue.get(item_id)
        in_queue = item is not None
        if item and not doc_name:
            doc_name = (item.get("artifacts") or {}).get("doc_name")

    return {
        "item_id": item_id,
        "has_summary": summary_path is not None,
        "in_queue": in_queue,
        "doc_name": doc_name,          # 没有 doc_name 就没进过 AgenticReader
        "has_index": bool(doc_name),
    }


def _delete_summary(item_id: str) -> dict:
    path = _summary_path(item_id)
    if path is None:
        return {"ok": True, "detail": "摘要文件不存在，跳过"}
    path.unlink()
    return {"ok": True, "detail": f"已删除 {path.name}"}


def _delete_queue(item_id: str) -> dict:
    with queue_transaction() as queue:
        if item_id not in queue:
            return {"ok": True, "detail": "queue 里没有这个条目，跳过"}
        del queue[item_id]
    return {"ok": True, "detail": "已从 queue 移除"}


def _delete_memory(item_id: str) -> dict:
    """item_id 就是 src/memory/adapters/ai_research.py 里约定的 source_id，
    直接按 (namespace, source_id) 查出所有行删除即可，不需要跨进程调用。"""
    from src.memory.vector_store import VectorStore

    vs = VectorStore(MEMORY_DB_DIR, get_embedding_dimensions("azure"))
    rows = vs.rows_for_source(NAMESPACE_AI_RESEARCH, item_id)
    if not rows:
        return {"ok": True, "detail": "memory 里没有这篇，跳过"}
    errors = []
    deleted = 0
    for row in rows:
        try:
            vs.delete(row["id"])
            deleted += 1
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    return {"ok": not errors, "detail": f"删除 {deleted}/{len(rows)} 行记忆" + (f"（{len(errors)} 项失败）" if errors else "")}


def _delete_index(doc_name: Optional[str]) -> dict:
    if not doc_name:
        return {"ok": True, "detail": "这条没有 doc_name（未进过 AgenticReader），跳过"}

    from src.core.document_management import DocumentRegistry

    registry = DocumentRegistry()
    doc = registry.get_by_name(doc_name)
    if not doc:
        return {"ok": True, "detail": "AgenticReader 里没有这篇，跳过"}

    result = registry.delete_all_files(doc["doc_id"], delete_source=True)
    registry.delete(doc["doc_id"])
    return {
        "ok": result.get("success", False),
        "detail": f"已删除索引与 {len(result.get('deleted_files', []))} 个关联文件"
                  + (f"（{len(result.get('errors', []))} 项失败）" if result.get("errors") else ""),
    }


async def delete_item(item_id: str, targets: list) -> dict:
    """按 targets 里勾选的项逐个删除，逐项报告结果。

    顺序上先删外部系统（memory / index）再删本地记账（summary / queue）：
    doc_name 要从 summary 里读，本地记录删早了就找不到该删哪篇索引了。
    """
    info = describe_delete_targets(item_id)
    results = {}

    if "memory" in targets:
        results["memory"] = await asyncio.to_thread(_delete_memory, item_id)
    if "index" in targets:
        results["index"] = await asyncio.to_thread(_delete_index, info["doc_name"])
    if "summary" in targets:
        results["summary"] = await asyncio.to_thread(_delete_summary, item_id)
    if "queue" in targets:
        results["queue"] = await asyncio.to_thread(_delete_queue, item_id)

    ok = all(r["ok"] for r in results.values())
    logger.info("删除条目 %s targets=%s ok=%s", item_id, targets, ok)
    return {"item_id": item_id, "ok": ok, "results": results}
