"""把一段原始文本压缩成"摘要(detail) + 简短摘要(abstract) + 关键词(keywords)
+ 重要度(importance)"四层表示——供 ingest 写入前调用。

改自 LLM-Memory 的 ingest_mid/llm_ingest.py，仅保留 ingest_chunk_metadata()/
summarize_source() 两个入口用到的部分：不含 quality_check 重试判官、
streaming agentic chunking、repo 专属的 commit diff 摘要。Prompt 文案本身
（含 KEYWORD_QUALITY_RUBRIC 关键词质量标准）原样保留——这是已经用真实数据
验证过的、独立于具体来源类型的通用标准，论文/文章摘要同样适用。

用 AgenticReader 自己的 LLMBase 调用 LLM（而不是 LLM-Memory 那边直接建
openai.OpenAI() client），复用已有的 provider/凭证/重试逻辑，不重新发明。
"""
import uuid
from typing import Any, Dict, List, Optional

from src.core.llm import LLMBase
from src.memory.parsing import (
    clean_text_response, parse_keyword_lines, parse_kv_lines, parse_sections, safe_float,
)

# ---- 关键词质量标准（与 KEYWORDS_ABSTRACT_PROMPT 共用同一份定义，只在此维护一处）----

KEYWORD_QUALITY_RUBRIC = """THE CORE TEST for every candidate keyword: "if I saw this term alone, with NO other context, could I
tell roughly what it's about?" A keyword must carry its own meaning.

Rules:
- Extract proper nouns, technical concepts, named methods/datasets/models, error TYPES, and concrete
  action verbs — anything a future search query would use. Keep each keyword a self-contained
  searchable term (a proper noun stays whole, e.g. "LanceDB"; split compound phrases into the terms
  someone would actually search by). Prefer a few extra words over an ambiguous short one.
- Do NOT extract standalone version numbers, arXiv IDs, or short identifiers with no attached concept
  (e.g. "v3", "2607.18264") — fold into ONE compound term that carries its own context if it identifies
  a specific searchable thing, otherwise drop it.
- Do NOT extract generic single words with no discriminating power (e.g. "model", "paper", "result").
  Generic words are fine ONLY as part of a specific compound term (e.g. "diffusion model").
- A failure, limitation, or "X does not work/is not supported" fact is NEVER optional — always emit a
  keyword for it, since that's exactly what someone searches for later.
- Aim for at least 5 keywords when the content contains that much distinct material.
- keyword REUSE: if the content is about a term already in the pool, use the EXACT spelling/casing
  from the pool. Only invent a new keyword when the pool genuinely lacks a fitting term.
- Handle mixed Chinese/English naturally. Substring matching supports Chinese of any length."""

CHUNK_SUMMARY_META_PROMPT = f"""You are a memory ingestion assistant. You are given one chunk of a raw source (a dimension of a paper/article QA breakdown, or a segment of a conversation), possibly preceded by a WHEN line giving its occurrence time.

Produce TWO outputs, in exactly this format — two section markers, nothing else outside them:

===SUMMARY===
<the detailed condensed record, plain prose>
===META===
importance: <a number between 0.0 and 1.0>
memory_type: <episodic or semantic>

For ===SUMMARY===: write a detailed condensed record of this chunk — key facts, methods, numbers, \
conclusions, limitations. Compress aggressively but NEVER drop concrete findings, numbers, or stated \
limitations. Typically 10-30% of the original length. If a WHEN line is given, weave the date \
naturally into the summary; do not invent a time if none is given. Write in the dominant language of \
the chunk (mixed Chinese/English handled naturally). No markdown fences or preamble inside the section.

For ===META===: judge the chunk's nature and value.
- episodic: a specific event/finding/decision tied to one document.
- semantic: general knowledge, patterns, or facts not tied to one specific document.
- importance: 0.9+ for critical findings/conclusions, 0.5-0.8 for useful context, <0.5 for minor detail."""

KEYWORDS_ABSTRACT_PROMPT = f"""You are a memory ingestion assistant. You are given a detailed summary (already condensed from the original source) and the EXISTING keyword pool for this scope.

Produce TWO outputs, in exactly this format — two section markers, nothing else outside them:

===KEYWORDS===
<one keyword per line>
===ABSTRACT===
<the compressed abstract, plain prose>

For ===KEYWORDS===: extract every searchable term needed to find this content again. One keyword per \
line, nothing else on those lines.

{KEYWORD_QUALITY_RUBRIC}

For ===ABSTRACT===: compress the summary further into a short abstract — this is the HIT layer: what \
gets embedded for semantic search and shown by default in search results. Max 200 tokens. Keep \
concrete findings/numbers/limitations over generic framing. Plain prose, no markdown fences or \
preamble inside the section. Write in the dominant language of the summary."""

SOURCE_SUMMARY_TEXT_PROMPT = """You are a memory ingestion assistant. You are given the chunk abstracts of ONE ingested source (one paper/article, or one conversation session), in order, possibly preceded by a WHEN line giving the source's overall time span.

Write a source-level summary: what this document covers overall, its core contribution/conclusion, \
and any major limitation. This is the DETAIL layer, returned when a user drills down.

If a WHEN line is given, open the summary by grounding it in that date so a reader knows when this \
happened. Do not invent a time if none is given.

Output ONLY the summary text itself — plain prose, no JSON, no markdown fences, no preamble. Write in \
the dominant language of the source (mixed Chinese/English handled naturally)."""

SOURCE_IMPORTANCE_PROMPT = """You are a memory ingestion assistant. You are given the chunk abstracts of ONE ingested source, in order. Rate the source as a whole.

Output EXACTLY one line, nothing else — no JSON, no markdown, no explanation:
importance: <a number between 0.0 and 1.0>

Sources with substantial findings/conclusions score higher (0.9+); thin or inconclusive sources score lower (<0.5)."""


def _when_prefix(occurred_at: Optional[str] = None) -> str:
    if not occurred_at:
        return ""
    return f"WHEN: {occurred_at}\n\n"


async def _call(llm: LLMBase, system_prompt: str, user_content: str) -> str:
    """跑一次一次性 LLM 调用。session_id 每次用新 uuid，避免多次 chunk
    condense 之间的对话历史互相累积（每次调用在语义上都是独立的一次性
    请求，不是多轮对话）。"""
    prompt = f"{system_prompt}\n\n{user_content}"
    session_id = f"memory_condense_{uuid.uuid4().hex[:12]}"
    response = await llm.async_call_llm_chain(role="", input_prompt=prompt, session_id=session_id)
    llm.message_histories.pop(session_id, None)
    return response or ""


async def ingest_chunk_metadata(
    llm: LLMBase,
    chunk_text: str,
    keyword_pool: Optional[List[str]] = None,
    occurred_at: Optional[str] = None,
) -> Dict[str, Any]:
    """把一个 chunk 压缩成 summary(detail) + abstract + keywords + importance
    + memory_type。两次批量调用（而不是四次单字段调用）：第一次产出
    summary+importance/memory_type，第二次基于 summary 产出 keywords+abstract。
    """
    pool = sorted(keyword_pool) if keyword_pool else []
    when = _when_prefix(occurred_at)

    sections = parse_sections(
        await _call(llm, CHUNK_SUMMARY_META_PROMPT, f"{when}Chunk to ingest:\n\n{chunk_text}"),
        tags=["SUMMARY", "META"],
    )
    summary = clean_text_response(sections.get("SUMMARY", "")) or chunk_text.strip()[:2000]
    imp_result = parse_kv_lines(sections.get("META", ""))

    pool_str = ", ".join(pool) if pool else "(empty — none yet)"
    user_content = f"Existing keyword pool (prefer reusing these):\n{pool_str}\n\nDetailed summary:\n\n{summary}"
    ka_sections = parse_sections(
        await _call(llm, KEYWORDS_ABSTRACT_PROMPT, user_content), tags=["KEYWORDS", "ABSTRACT"],
    )
    keywords = parse_keyword_lines(ka_sections.get("KEYWORDS", ""))
    abstract = clean_text_response(ka_sections.get("ABSTRACT", "")) or summary[:800]

    return {
        "summary": summary,
        "abstract": abstract,
        "keywords": keywords,
        "importance": safe_float(imp_result, "importance", 0.6),
        "memory_type": imp_result.get("memory_type", "episodic"),
    }


async def summarize_source(
    llm: LLMBase,
    chunk_abstracts: List[str],
    keyword_pool: Optional[List[str]] = None,
    occurred_at: Optional[str] = None,
) -> Dict[str, Any]:
    """把一个 source 的所有 chunk abstract 压缩成整篇摘要（summary+abstract+
    keywords+importance）。"""
    pool = sorted(keyword_pool) if keyword_pool else []
    numbered = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(chunk_abstracts))
    user_content = f"{_when_prefix(occurred_at)}Chunk abstracts of the source, in order:\n{numbered}"

    summary = clean_text_response(await _call(llm, SOURCE_SUMMARY_TEXT_PROMPT, user_content))
    summary = summary or " / ".join(chunk_abstracts)[:2000]
    imp_result = parse_kv_lines(await _call(llm, SOURCE_IMPORTANCE_PROMPT, user_content))

    pool_str = ", ".join(pool) if pool else "(empty — none yet)"
    ka_user = f"Existing keyword pool (prefer reusing these):\n{pool_str}\n\nDetailed summary:\n\n{summary}"
    ka_sections = parse_sections(
        await _call(llm, KEYWORDS_ABSTRACT_PROMPT, ka_user), tags=["KEYWORDS", "ABSTRACT"],
    )
    keywords = parse_keyword_lines(ka_sections.get("KEYWORDS", ""))
    abstract = clean_text_response(ka_sections.get("ABSTRACT", "")) or summary[:800]

    return {
        "summary": summary,
        "abstract": abstract,
        "keywords": keywords,
        "importance": safe_float(imp_result, "importance", 0.6),
    }
