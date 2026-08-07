"""Memory 浏览的数据层——供 /memory 页面查看 src.memory 向量库的内容
（有哪些 namespace、各自多少条、每条具体是什么）。

改自 ai-research-pipeline 的 webapp/services/_memory_browse_worker.py。
原实现要跨 venv subprocess 调用 LLM-Memory（因为 webapp 进程不能 import
它的 lancedb 依赖）；合并进 AgenticReader 后 src.memory.vector_store 与
本项目其余代码同进程运行，直接调用即可，不再需要 subprocess/worker 脚本。

与原实现的一处差异：src/memory/vector_store.py 是单层记忆（不区分
mid/long tier，见合并计划），所以 build_overview()/build_namespace_list()
的返回形状去掉了 tier 相关字段。

只读接口，不改 memory 库任何数据。
"""
import asyncio
from typing import Any, Dict

from src.memory.config import MEMORY_DB_DIR, get_embedding_dimensions
from src.memory.vector_store import VectorStore, is_summary_row, load_json_list


def _vs() -> VectorStore:
    return VectorStore(MEMORY_DB_DIR, get_embedding_dimensions("azure"))


def _build_overview() -> Dict[str, Any]:
    """全库统计：总量 + 每个 namespace 的条数/来源类型分布。"""
    vs = _vs()
    rows = vs.all_rows("*")
    by_ns: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        ns = row.get("namespace") or "default"
        entry = by_ns.setdefault(ns, {
            "namespace": ns, "total": 0, "_imp_sum": 0.0,
            "source_types": {}, "latest_created_at": "",
        })
        entry["total"] += 1
        entry["_imp_sum"] += float(row.get("importance", 0.0))
        st = row.get("source_type") or "unknown"
        entry["source_types"][st] = entry["source_types"].get(st, 0) + 1
        created = row.get("created_at") or ""
        if created > entry["latest_created_at"]:
            entry["latest_created_at"] = created

    namespaces = []
    for entry in by_ns.values():
        entry["avg_importance"] = round(entry["_imp_sum"] / entry["total"], 3) if entry["total"] else 0
        del entry["_imp_sum"]
        namespaces.append(entry)
    namespaces.sort(key=lambda e: e["latest_created_at"], reverse=True)

    return {
        "total": len(rows),
        "total_namespaces": len(namespaces),
        "namespaces": namespaces,
    }


def _build_namespace_list(namespace: str) -> Dict[str, Any]:
    """某个 namespace 下的记忆，按 source_id 分组——一次 ingest 进来的一个
    来源（一篇论文/一段对话）在 UI 上是一张可展开的卡片，而不是几十张
    互不相干的 chunk 卡片。"""
    vs = _vs()
    rows = vs.all_rows(namespace)
    groups: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        item = {
            "id": row.get("id"),
            "abstract": row.get("abstract", ""),
            "importance": row.get("importance", 0.5),
            "created_at": row.get("created_at", ""),
            "occurred_at": row.get("occurred_at") or row.get("created_at", ""),
            "keywords": load_json_list(row.get("keywords")),
            "is_summary": is_summary_row(row),
        }
        sid = row.get("source_id") or row.get("id")
        group = groups.setdefault(sid, {
            "source_id": sid,
            "source_type": row.get("source_type") or "unknown",
            "namespace": row.get("namespace"),
            "items": [],
        })
        group["items"].append(item)

    result = []
    for group in groups.values():
        group["items"].sort(key=lambda it: it.get("created_at") or "")
        group["count"] = len(group["items"])
        group["latest_created_at"] = max((it.get("created_at") or "") for it in group["items"])
        # source-summary 行（chunk_hash 为空）是整组最好的一句话描述；
        # 没有这一行时退化用组内第一条。
        summary_item = next((it for it in group["items"] if it["is_summary"]), None)
        group["representative_abstract"] = (summary_item or group["items"][0])["abstract"]
        result.append(group)
    result.sort(key=lambda g: g["latest_created_at"], reverse=True)

    return {"namespace": namespace, "total": len(rows), "groups": result}


def _build_detail(memory_id: str) -> Dict[str, Any]:
    """单条记忆的全字段（列表接口只给精简形状，抽屉里要看完整内容）。"""
    vs = _vs()
    row = vs.get_by_ids([memory_id]).get(memory_id)
    if row is None:
        return {"found": False, "id": memory_id}
    return {
        "found": True,
        "id": row.get("id"),
        "namespace": row.get("namespace"),
        "memory_type": row.get("memory_type"),
        "importance": row.get("importance"),
        "created_at": row.get("created_at"),
        "occurred_at": row.get("occurred_at"),
        "source_type": row.get("source_type"),
        "source_id": row.get("source_id"),
        "abstract": row.get("abstract"),
        "detail": row.get("detail"),
        "raw_source": row.get("raw_source"),
        "keywords": load_json_list(row.get("keywords")),
    }


def _delete_memory(memory_id: str) -> Dict[str, Any]:
    vs = _vs()
    vs.delete(memory_id)
    return {"ok": True, "id": memory_id}


async def fetch_overview() -> Dict[str, Any]:
    return await asyncio.to_thread(_build_overview)


async def fetch_namespace(namespace: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_build_namespace_list, namespace)


async def fetch_detail(memory_id: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_build_detail, memory_id)


async def delete_memory(memory_id: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_delete_memory, memory_id)
