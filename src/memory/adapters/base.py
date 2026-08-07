"""Source adapter 接口：每种输入类型（论文/文章摘要 JSON、webapp 对话
session JSON）各自实现 parse/chunk，ingest 流程本身对所有类型保持一致。

改自 LLM-Memory 的 ingest_mid/adapters/base.py，去掉了 repo 专属的
is_excluded_row/post_ingest（AgenticReader 目前只有两种来源，都不需要）。
"""
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Chunk:
    """一个存储单元。text 落盘为记忆行的 raw_source，meta 是 adapter 自定义的
    附加信息（时间戳、维度标记等）。"""
    text: str
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UpdatePlan:
    """SourceAdapter.update_plan() 的返回值。

    fresh     — 需要真正 ingest（走 LLM condense + 写库）的 chunk。
    stale_ids — 不再对应任何当前内容、需要删除的旧记忆行 id（按基类默认
                实现，永远为空——只有需要"淘汰旧尾块"语义的 adapter 才会
                产生非空值，如 webapp_chat）。
    """
    fresh: List[Chunk]
    stale_ids: List[str] = field(default_factory=list)


class SourceAdapter(ABC):
    """每种来源类型要实现的接口。"""

    source_type: str = "base"

    @abstractmethod
    def source_id(self, path: str) -> str:
        """这个来源的稳定标识（如论文的 item_id，或对话的 session_id）。"""

    @abstractmethod
    def parse(self, path: str) -> List[Dict[str, Any]]:
        """原始文件 -> 有序的逻辑单元列表。"""

    @abstractmethod
    def chunk(self, units: List[Dict[str, Any]]) -> List[Chunk]:
        """逻辑单元 -> 存储 chunk。"""

    def update_plan(self, existing_rows: List[Dict[str, Any]], chunks: List[Chunk]) -> UpdatePlan:
        """默认实现：按内容 hash 做去重（新内容追加，不做覆盖判断）。
        适合"一次性快照，重复处理产出相同内容不应重复写入"的场景
        （ai_research）。需要"淘汰旧尾块"语义的来源（webapp_chat，持续
        增长的对话）会覆写这个方法。"""
        existing_hashes = {r["chunk_hash"] for r in existing_rows if r.get("chunk_hash")}
        fresh = []
        for c in chunks:
            h = hashlib.sha256(c.text.encode("utf-8")).hexdigest()[:16]
            c.meta["chunk_hash"] = h
            if h not in existing_hashes:
                fresh.append(c)
        return UpdatePlan(fresh=fresh)
