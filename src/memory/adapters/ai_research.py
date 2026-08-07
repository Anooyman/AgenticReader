"""论文/文章摘要 JSON（pipeline/process_pdf_queue.py、process_web_queue.py
产出的 state/summaries/{pdf,web}/*.json）的 adapter。

改自 LLM-Memory 的 ingest_mid/adapters/ai_research.py。chunk 策略：**每个
QA 维度一个 chunk**（外加一个 qa_brief 速览卡片 chunk）——而不是整篇合并成
一个 chunk。原因：PDF 摘要总量可达数万字符，远超单 chunk 上限，按维度切分
后每个维度语义完整（"实验结果"/"核心创新"各自成块），检索命中更精确；整篇
召回由 ingest 自动生成的 source-summary 行承担。

source_id 直接用 item_id（PDF 用去版本号的 arxiv id，web 用 URL 的
sha256 前16位）——与 AgenticReader 的 doc_name 是同一个值（见
pipeline/process_pdf_queue.py 的 doc_name=item.item_id 约定），命中记忆后
可以直接反查回原文档，衔接 deep_dive_document 工具。

occurred_at = generated_at（流水线处理时间）。
"""
import json
from typing import Any, Dict, List

from .base import Chunk, SourceAdapter

QA_LABELS = {
    "full_content": "完整内容脉络",
    "innovation": "核心创新点",
    "experiments": "实验设置与结果",
    "algorithm_detail": "算法/方法实现细节",
    "advantages": "优势与局限",
    "key_takeaways": "重要结论",
    "overview": "内容概述",
    "key_claims": "主要观点",
    "evidence_quality": "论据/来源可信度",
    "relevance": "参考价值",
    "caveats": "需谨慎对待之处",
}

CHUNK_MAX_CHARS = 12000


def _split_paragraph_aware(text: str, hard_max: int) -> List[str]:
    """按段落边界（"\\n\\n"）切分超长文本，贪心装箱到 hard_max；单段仍超长
    时才硬切（句中截断只在这种退化情况下发生，不是常规路径）。"""
    if len(text) <= hard_max:
        return [text]
    pieces: List[str] = []
    buf = ""
    for para in text.split("\n\n"):
        while len(para) > hard_max:
            if buf:
                pieces.append(buf)
                buf = ""
            pieces.append(para[:hard_max])
            para = para[hard_max:]
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) > hard_max:
            pieces.append(buf)
            buf = para
        else:
            buf = candidate
    if buf:
        pieces.append(buf)
    return pieces


class AIResearchAdapter(SourceAdapter):
    source_type = "ai_research"

    def source_id(self, path: str) -> str:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data["item_id"]

    def parse(self, path: str) -> List[Dict[str, Any]]:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        units: List[Dict[str, Any]] = []
        ts = data.get("generated_at", "")

        title = data.get("title") or data.get("url", "")
        header_lines = [f"# {title}"]
        meta_parts = []
        if data.get("type"):
            meta_parts.append(f"类型: {data['type']}")
        if data.get("url"):
            meta_parts.append(f"来源: {data['url']}")
        if data.get("coverage_date"):
            meta_parts.append(f"覆盖日期: {data['coverage_date']}")
        if meta_parts:
            header_lines.append(" | ".join(meta_parts))
        header = "\n".join(header_lines)

        qa_brief = data.get("qa_brief") or {}
        brief_lines = [f"- {QA_LABELS.get(k, k)}: {v}" for k, v in qa_brief.items()
                       if v and str(v).strip()]
        if brief_lines:
            units.append({"ts": ts, "role": "brief", "header": header,
                          "text": "【速览】\n" + "\n".join(brief_lines)})

        for key, answer in (data.get("qa") or {}).items():
            if not answer or not str(answer).strip():
                continue
            label = QA_LABELS.get(key, key)
            units.append({"ts": ts, "role": "qa", "header": header,
                          "dimension": key, "text": f"【{label}】\n{answer}"})

        return units

    def chunk(self, units: List[Dict[str, Any]]) -> List[Chunk]:
        chunks: List[Chunk] = []
        for u in units:
            full_text = f"{u['header']}\n\n{u['text']}"
            for piece in _split_paragraph_aware(full_text, CHUNK_MAX_CHARS):
                meta: Dict[str, Any] = {"start_ts": u["ts"], "role": u["role"]}
                if u.get("dimension"):
                    meta["dimension"] = u["dimension"]
                chunks.append(Chunk(text=piece, meta=meta))
        return chunks

    # update_plan()：用基类默认的 hash-based append-only 逻辑即可——同一篇
    # 论文/文章重复处理产出相同内容不会重复写入。
