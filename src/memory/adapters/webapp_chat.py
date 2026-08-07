"""AgenticReader chat（Orchestrator 驱动，UI 见 /chat）的 adapter。改自
LLM-Memory 的 ingest_mid/adapters/webapp_chat.py。

源文件是单个 session JSON（每个对话一个文件，SessionManager 落盘的位置，
见 src/ui/backend/services/session_manager.py）：
    {"session_id": ..., "title": ..., "doc_name": ...|null,
     "created_at": ..., "updated_at": ...,
     "messages": [{"role", "content", "timestamp", "sources_used"}, ...]}

与 ai_research adapter 不同：这里的对话是持续增长的、有真实时间语义的会话
记录，复用 time_gap_chunk 分块策略，而不是"每个维度一个 chunk"。
"""
import hashlib
import json
import os
from typing import Any, Dict, List

from .base import Chunk, SourceAdapter, UpdatePlan
from .chunking import time_gap_chunk


class WebappChatAdapter(SourceAdapter):
    source_type = "webapp_chat"

    def source_id(self, path: str) -> str:
        """session_id 是这段对话的稳定标识，优先取文件内容里的 session_id，
        取不到才退回文件名（生产环境两者本来就一致，session 落盘路径就是
        {session_id}.json）。"""
        try:
            with open(path, encoding="utf-8") as f:
                session_id = json.load(f).get("session_id")
            if session_id:
                return str(session_id)
        except (json.JSONDecodeError, OSError, AttributeError):
            pass
        return os.path.splitext(os.path.basename(path))[0]

    def parse(self, path: str) -> List[Dict[str, Any]]:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        messages = data.get("messages") or []
        units: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "")
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            text = content
            sources = msg.get("sources_used") or []
            if sources:
                text = f"{text}\n[sources: {', '.join(sources)}]"
            units.append({"ts": msg.get("timestamp", ""), "role": role, "text": text})

        if not units:
            return []

        # 会话头拼进第一条 unit，单看一条 chunk 也知道这是哪段对话在聊什么。
        header_parts = [f"【对话】{data.get('title') or '(无标题)'}"]
        meta_bits = []
        if data.get("doc_name"):
            meta_bits.append(f"聚焦文档: {data['doc_name']}")
        if data.get("created_at"):
            meta_bits.append(f"创建于: {data['created_at']}")
        if meta_bits:
            header_parts.append(" | ".join(meta_bits))
        units[0]["text"] = "\n".join(header_parts) + "\n\n" + units[0]["text"]

        return units

    def chunk(self, units: List[Dict[str, Any]]) -> List[Chunk]:
        return time_gap_chunk(units)

    def update_plan(self, existing_rows: List[Dict[str, Any]], chunks: List[Chunk]) -> UpdatePlan:
        """Hash 去重 + 清理被取代的旧尾块。

        不能用基类的纯 append-only 默认实现：一个还在进行中的会话会被反复
        ingest，而 time_gap_chunk 的最后一块是"未满 target 就先攒着"的部分
        块——每追加几轮对话，这一块的内容就变一次，hash 随之改变。基类只按
        hash 判新、从不产生 stale_ids，会导致每次 ingest 都插入一条新的尾块
        行，旧的短版本前身留在库里，造成同一段对话的近重复记录污染检索。

        已经攒满 target 被 flush 掉的前面那些块是稳定的（同样的消息前缀总是
        切出同样的块），按 hash 命中、跳过，不重复付出 LLM 抽取成本。每次
        ingest 真正重算的只有尾块这一块。

        source-summary 行（chunk_hash 为空）排除在清理之外。
        """
        fresh: List[Chunk] = []
        current_hashes = set()
        for c in chunks:
            h = hashlib.sha256(c.text.encode("utf-8")).hexdigest()[:16]
            c.meta["chunk_hash"] = h
            current_hashes.add(h)

        existing_hashes = set()
        stale_ids: List[str] = []
        for r in existing_rows:
            chunk_hash = r.get("chunk_hash")
            if not chunk_hash:
                continue
            existing_hashes.add(chunk_hash)
            if chunk_hash not in current_hashes:
                stale_ids.append(r["id"])

        for c in chunks:
            if c.meta["chunk_hash"] not in existing_hashes:
                fresh.append(c)

        return UpdatePlan(fresh=fresh, stale_ids=stale_ids)
