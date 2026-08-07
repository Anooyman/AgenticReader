"""Typed-source ingestion pipeline：source 文件 -> chunk -> LLM condense ->
embed -> 写入 VectorStore。

改自 LLM-Memory 的 ingest_mid/ingest.py，仅保留 ai-research-pipeline 实际
用到的部分：单层记忆（不区分 mid/long tier）、顺序处理（不做并发批量抽取
——AgenticReader 单篇文档的 chunk 数量小，串行足够，不需要引入线程池），
不含 quality_check 判官重试、streaming agentic chunking、repo 专属逻辑。

同一来源重复 ingest 是幂等的：已写入的 chunk 按内容 hash 跳过（不重复付出
LLM 抽取成本），source-summary 行（整篇摘要）每次重新生成替换旧的。
"""
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.llm import LLMBase
from src.memory.adapters import get_adapter
from src.memory.config import MEMORY_DB_DIR, get_embedding_dimensions
from src.memory.llm_condense import ingest_chunk_metadata, summarize_source
from src.memory.vector_store import VectorStore, dump_json_list, is_summary_row

LOCK_DIR = os.path.join(MEMORY_DB_DIR, ".ingest_locks")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_mtime_iso(path: str) -> str:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()
    except OSError:
        return _now()


def _occurred_at(chunk_meta: Dict[str, Any], fallback: str) -> str:
    return chunk_meta.get("start_ts") or fallback


@contextmanager
def _source_lock(namespace: str, source_id: str):
    """同一 (namespace, source_id) 的 ingest 排他锁——防止同一篇文档/同一
    session 被并发 ingest 两次时互相覆盖（chat_ingest 的定期扫描 worker 和
    手动触发的补灌可能同时命中同一个 source_id）。"""
    import fcntl

    os.makedirs(LOCK_DIR, exist_ok=True)
    key = hashlib.sha256(f"{namespace}:{source_id}".encode("utf-8")).hexdigest()[:16]
    lock_path = os.path.join(LOCK_DIR, f"{key}.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


async def _embed(llm: LLMBase, text: str) -> List[float]:
    return await llm.embedding_model.aembed_query(text)


async def ingest_source(
    path: str,
    source_type: str,
    namespace: str,
    provider: str = "openai",
    source_id: Optional[str] = None,
) -> dict:
    """跑一次完整的 ingest 流程，返回一份处理报告 dict：
    {"source_type", "source_id", "namespace", "units", "chunks_total",
     "chunks_added", "chunks_skipped", "chunks_deleted", "chunks_failed",
     "summary_id"}
    """
    adapter = get_adapter(source_type)
    sid = source_id or adapter.source_id(path)

    units = adapter.parse(path)
    chunks = adapter.chunk(units)

    report: Dict[str, Any] = {
        "source_type": source_type,
        "source_id": sid,
        "namespace": namespace,
        "units": len(units),
        "chunks_total": len(chunks),
        "chunks_added": 0,
        "chunks_skipped": 0,
        "chunks_deleted": 0,
        "chunks_failed": [],
        "summary_id": None,
    }
    if not chunks:
        return report

    llm = LLMBase(provider=provider)
    dimensions = get_embedding_dimensions(provider)
    vs = VectorStore(MEMORY_DB_DIR, dimensions)

    with _source_lock(namespace, sid):
        existing_rows = vs.rows_for_source(namespace, sid)
        plan = adapter.update_plan(existing_rows, chunks)
        fresh = plan.fresh
        report["chunks_skipped"] = len(chunks) - len(fresh)
        report["chunks_deleted"] = len(plan.stale_ids)

        for stale_id in plan.stale_ids:
            try:
                vs.delete(stale_id)
            except Exception as e:
                report.setdefault("delete_failed", []).append({"id": stale_id, "error": str(e)})

        pool_set = set(vs.keyword_pool(namespace))
        now = _now()
        file_fallback = _file_mtime_iso(path)

        # 顺序处理每个 fresh chunk：condense -> embed -> 立即写入。逐条写入
        # （而不是先抽取全部再统一写）保证中途中断只损失还在处理中的那条，
        # 已完成的 chunk 已经落盘。
        for c in fresh:
            occurred_at = _occurred_at(c.meta, file_fallback)
            try:
                meta = await ingest_chunk_metadata(
                    llm, c.text, keyword_pool=sorted(pool_set), occurred_at=occurred_at,
                )
                vector = await _embed(llm, meta["abstract"])
            except Exception as e:
                report["chunks_failed"].append({"chunk_hash": c.meta["chunk_hash"], "error": str(e)})
                continue

            record = {
                "id": str(uuid.uuid4()),
                "vector": vector,
                "namespace": namespace,
                "memory_type": meta["memory_type"],
                "abstract": meta["abstract"],
                "detail": meta["summary"],
                "raw_source": c.text,
                "keywords": dump_json_list(meta["keywords"]),
                "importance": meta["importance"],
                "created_at": now,
                "source_type": source_type,
                "source_id": sid,
                "chunk_hash": c.meta["chunk_hash"],
                "occurred_at": occurred_at,
            }
            vs.add(record)
            pool_set.update(meta["keywords"])
            report["chunks_added"] += 1

        # ---- 重新生成整篇摘要行（chunk_hash == ""）----
        rows = vs.rows_for_source(namespace, sid)
        chunk_rows = sorted(
            (r for r in rows if r.get("chunk_hash")),
            key=lambda r: r.get("occurred_at") or r.get("created_at", ""),
        )
        old_summaries = [r for r in rows if is_summary_row(r)]
        chunk_times = [r.get("occurred_at") or r.get("created_at", "") for r in chunk_rows]
        source_occurred_at = chunk_times[0] if chunk_times else file_fallback
        time_range = (source_occurred_at if len(set(chunk_times)) <= 1
                     else f"{chunk_times[0]} to {chunk_times[-1]}")

        if chunk_rows:
            try:
                smeta = await summarize_source(
                    llm, [r.get("abstract", "") for r in chunk_rows],
                    keyword_pool=sorted(pool_set), occurred_at=time_range,
                )
            except Exception as e:
                report["summary_error"] = str(e)
            else:
                min_imp = 0.7
                svector = await _embed(llm, smeta["abstract"])
                summary_id = str(uuid.uuid4())
                vs.add({
                    "id": summary_id,
                    "vector": svector,
                    "namespace": namespace,
                    "memory_type": "episodic",
                    "abstract": smeta["abstract"],
                    "detail": smeta["summary"],
                    "raw_source": json.dumps({"chunk_ids": [r["id"] for r in chunk_rows]}, ensure_ascii=False),
                    "keywords": dump_json_list(smeta["keywords"]),
                    "importance": max(smeta["importance"], min_imp),
                    "created_at": _now(),
                    "source_type": source_type,
                    "source_id": sid,
                    "chunk_hash": "",
                    "occurred_at": source_occurred_at,
                })
                for r in old_summaries:
                    vs.delete(r["id"])
                report["summary_id"] = summary_id

        return report
