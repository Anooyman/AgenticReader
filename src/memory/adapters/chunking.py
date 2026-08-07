"""按时间/字符数分块的共享算法，供 webapp_chat adapter 使用（持续增长的对话
需要按时间间隔切分，与 ai_research 的"每维度一个 chunk"策略不同——一次性
快照 vs 持续对话，时间语义不同）。改自 LLM-Memory 的
ingest_mid/adapters/chunking.py。
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import Chunk

CHUNK_TARGET_CHARS = 8000
CHUNK_MAX_CHARS = 12000
TIME_GAP_MINUTES = 30


def _parse_ts(ts: Optional[str]):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def time_gap_chunk(units: List[Dict[str, Any]]) -> List[Chunk]:
    """累积"[HH:MM] ROLE: text"格式的行直到 chunk_target_chars，遇到超过
    time_gap_minutes 的时间间隔强制断开，超过 chunk_max_chars 硬切。"""
    chunks: List[Chunk] = []
    buf: List[str] = []
    size = 0
    start_ts = end_ts = ""
    last_dt = None

    def _flush():
        nonlocal buf, size, start_ts, end_ts
        if buf:
            chunks.append(Chunk(
                text="\n".join(buf),
                meta={"start_ts": start_ts, "end_ts": end_ts, "lines": len(buf)},
            ))
        buf, size, start_ts, end_ts = [], 0, "", ""

    for u in units:
        dt = _parse_ts(u["ts"])
        gap_break = (
            last_dt is not None and dt is not None
            and (dt - last_dt).total_seconds() > TIME_GAP_MINUTES * 60
        )
        if buf and (size >= CHUNK_TARGET_CHARS or gap_break):
            _flush()

        role = u["role"].upper()
        ts_label = f"[{dt.strftime('%Y-%m-%d %H:%M')}] " if dt is not None else ""
        line = f"{ts_label}{role}: {u['text']}"

        while len(line) > CHUNK_MAX_CHARS:
            buf.append(line[:CHUNK_MAX_CHARS])
            _flush()
            line = line[CHUNK_MAX_CHARS:]

        if not buf:
            start_ts = u["ts"]
        buf.append(line)
        size += len(line)
        end_ts = u["ts"]
        if dt is not None:
            last_dt = dt

    _flush()
    return chunks
