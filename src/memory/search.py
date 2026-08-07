"""Agentic 检索：多轮工具调用循环，LLM 自主决定调用哪个检索工具、调用
几轮、以及当前结果是否足以回答问题（通过每轮强制的 assess_sufficiency
步骤，由编排代码而非模型自行判断是否要停）。

改自 LLM-Memory 的 retrieval/agent_search.py，保留其核心机制（多工具+
自我评估的 ReAct 循环），去掉了针对更大规模/多来源记忆库设计的部分：
query 改写、话题聚类 synthesis、相对时间解析（resolve_time_range）、
list_authors/time_search（这些是通用长期记忆场景的能力，不在本次合并
范围内——参见合并计划"不搬的部分"）。检索工具集是
semantic_search/keyword_search/list_keywords/list_by_source 四个。

用 AgenticReader 自己的 LLMBase.get_chat_model_with_tools()（LangChain
bind_tools）驱动工具调用循环，而不是像 LLM-Memory 那样直接用 openai SDK
的裸 dict 工具调用格式——复用本项目已有的 LLM 抽象层（src/services/
mcp_client.py 的 MCPClient._process_with_tools 是同一个模式的先例）。
"""
import logging
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.core.llm import LLMBase
from src.memory.config import MEMORY_DB_DIR, get_embedding_dimensions
from src.memory.vector_store import VectorStore, shape_result_row

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 4
_MAX_KEYWORD_POOL_IN_TOOL_RESULT = 300

# ---- 工具定义（LangChain bind_tools 接受的 JSON Schema 格式）----

RETRIEVAL_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "Search memories by meaning/similarity. Best for conceptual or "
                            "paraphrased questions where exact keywords are unknown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language search text to embed."},
                    "namespace": {"type": "string", "description": "Limit to one namespace, or omit for all."},
                    "top_k": {"type": "integer", "description": "Max results, default 8."},
                    "source_type": {"type": "string", "description": "Optional filter: ai_research | webapp_chat."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "keyword_search",
            "description": "Search memories by exact keyword/substring match. Best when the question "
                            "names specific terms, proper nouns, or jargon likely to appear verbatim.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {"type": "array", "items": {"type": "string"},
                                 "description": "Terms to match. Call list_keywords first if unsure what exists."},
                    "namespace": {"type": "string"},
                    "top_k": {"type": "integer"},
                    "source_type": {"type": "string", "description": "Optional filter: ai_research | webapp_chat."},
                },
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_keywords",
            "description": "List the known keyword vocabulary for a namespace (or all namespaces). "
                            "Call this before keyword_search if unsure which exact terms exist.",
            "parameters": {"type": "object", "properties": {"namespace": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_by_source",
            "description": "Fetch every memory chunk belonging to one ingested source (e.g. one "
                            "paper/article, or one conversation session), given its source_id. Use "
                            "after a search result names a source_id you want full context on.",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}, "source_id": {"type": "string"}},
                "required": ["source_id"],
            },
        },
    },
]

ASSESS_SUFFICIENCY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "assess_sufficiency",
        "description": "Judge whether the search results gathered so far are sufficient to answer "
                        "the ORIGINAL question. You MUST call this after every retrieval round.",
        "parameters": {
            "type": "object",
            "properties": {
                "sufficient": {"type": "boolean",
                               "description": "True if the results so far actually answer the question."},
                "missing_aspects": {"type": "string",
                                    "description": "If not sufficient, what specifically is missing. Empty if sufficient."},
                "next_action": {"type": "string", "enum": ["stop_and_answer", "broaden_query", "switch_strategy"],
                                 "description": "stop_and_answer if sufficient; otherwise broaden_query (same "
                                                 "approach, wider net) or switch_strategy (try a different tool)."},
            },
            "required": ["sufficient", "next_action"],
        },
    },
}

SYSTEM_PROMPT = """You are a memory-retrieval agent for a personal research memory system (paper/article \
summaries and prior conversation notes). Given a question, use the search tools to find relevant stored \
memories, then answer based on what you find.

If the question has multiple independent parts, search for each part separately — you may call \
multiple tools in one turn.

After every round of tool calls, you will be asked to assess whether the results are sufficient via \
assess_sufficiency — you MUST call it, be honest, do not claim sufficiency just to finish quickly.

Once you have enough to answer, or you're confident nothing relevant exists, give a final answer in \
plain text (no more tool calls) — cite doc_name/source_id when a specific document backs a claim, so \
the caller can offer to look deeper into that specific document if needed."""


def _trim_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """裁剪成喂给 LLM 判断相关性所需的最小信息（不含 detail/raw_source/vector）。"""
    out = []
    for r in rows:
        out.append({
            "id": r.get("id"),
            "abstract": r.get("abstract", ""),
            "source_type": r.get("source_type", ""),
            "source_id": r.get("source_id", ""),
            "occurred_at": r.get("occurred_at") or r.get("created_at", ""),
            "score": round(float(r.get("semantic_score") or r.get("keyword_score_normalized") or 0.0), 4),
        })
    return out


def _effective_namespace(requested: Any, default_namespace):
    """LLM 在某次 tool_call 里显式传的 namespace 优先；否则回退到调用方
    传入的默认限定范围（None/空 = 不限定，检索全部）。"""
    if requested:
        return requested
    return default_namespace


def dispatch_tool_call(name: str, args: Dict[str, Any], vs: VectorStore, llm: LLMBase,
                        default_namespace, all_seen: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """执行一次检索工具调用。绝不抛异常——任何失败都包成 {"error": ...}
    返回给模型，让它据此调整而不是让整个循环崩掉。"""
    try:
        namespace = _effective_namespace(args.get("namespace"), default_namespace)
        if name == "semantic_search":
            query = args["query"]
            vector = llm.embedding_model.embed_query(query)
            rows = vs.semantic_search(
                vector, namespace, top_k=int(args.get("top_k") or 8),
                source_type=args.get("source_type"),
            )
            for r in rows:
                all_seen[r["id"]] = r
            return {"count": len(rows), "results": _trim_rows(rows)}

        elif name == "keyword_search":
            keywords = args.get("keywords") or []
            rows = vs.keyword_search(
                keywords, namespace, top_k=int(args.get("top_k") or 10),
                source_type=args.get("source_type"),
            )
            for r in rows:
                all_seen[r["id"]] = r
            return {"count": len(rows), "results": _trim_rows(rows)}

        elif name == "list_keywords":
            pool = vs.keyword_pool(namespace)
            truncated = len(pool) > _MAX_KEYWORD_POOL_IN_TOOL_RESULT
            return {"count": len(pool), "keywords": pool[:_MAX_KEYWORD_POOL_IN_TOOL_RESULT], "truncated": truncated}

        elif name == "list_by_source":
            rows = vs.rows_for_source(namespace or "*", args["source_id"])
            for r in rows:
                all_seen[r["id"]] = r
            return {"count": len(rows), "results": _trim_rows(rows)}

        else:
            return {"error": f"unknown tool: {name}"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


async def agentic_search(
    query: str,
    namespace: Optional[List[str]] = None,
    provider: str = "openai",
    max_iterations: int = MAX_ITERATIONS,
) -> Dict[str, Any]:
    """跑一次多轮工具调用检索循环，返回
    {"answer": str, "results": [...], "iterations": int, "tool_calls_made": int}。

    namespace=None（或省略）检索所有 namespace；传字符串列表限定检索范围
    （例如只查 "ai-research"）。
    """
    llm = LLMBase(provider=provider)
    dimensions = get_embedding_dimensions(provider)
    vs = VectorStore(MEMORY_DB_DIR, dimensions)

    all_seen: Dict[str, Dict[str, Any]] = {}
    tool_calls_made = 0

    messages: List[Any] = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=query),
    ]

    def _ranked_results() -> List[Dict[str, Any]]:
        for r in all_seen.values():
            r["score"] = float(r.get("semantic_score") or r.get("keyword_score_normalized") or 0.0)
        ranked = sorted(all_seen.values(), key=lambda r: r["score"], reverse=True)
        return [shape_result_row(r, include_raw=True) for r in ranked]

    for iteration in range(1, max_iterations + 1):
        model = llm.get_chat_model_with_tools(tools=RETRIEVAL_TOOLS)
        response = await model.ainvoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            # 模型没有调用任何工具就直接给出了文本回答——视为完成。
            return {
                "answer": response.content or "",
                "results": _ranked_results(),
                "iterations": iteration,
                "tool_calls_made": tool_calls_made,
            }

        for call in tool_calls:
            tool_calls_made += 1
            result = dispatch_tool_call(call["name"], call.get("args") or {}, vs, llm, namespace, all_seen)
            messages.append(ToolMessage(content=_to_json(result), tool_call_id=call["id"]))

        # ---- 强制的自我评估步骤：本轮结果是否足以回答问题 ----
        assess_model = llm.get_chat_model_with_tools(tools=[ASSESS_SUFFICIENCY_TOOL])
        assess_response = await assess_model.ainvoke(
            messages + [HumanMessage(content="Call assess_sufficiency now.")]
        )
        assess_calls = getattr(assess_response, "tool_calls", None) or []
        sufficient = False
        if assess_calls:
            sufficient = bool(assess_calls[0].get("args", {}).get("sufficient"))

        if sufficient or iteration == max_iterations:
            final_model = llm.get_chat_model_with_tools(tools=None)
            final_response = await final_model.ainvoke(
                messages + [HumanMessage(
                    content="Give your final answer now in plain text, no more tool calls."
                )]
            )
            return {
                "answer": final_response.content or "",
                "results": _ranked_results(),
                "iterations": iteration,
                "tool_calls_made": tool_calls_made,
            }

        missing = assess_calls[0].get("args", {}).get("missing_aspects", "") if assess_calls else ""
        messages.append(HumanMessage(
            content=f"Current results are not yet sufficient. Missing: {missing or '(unspecified)'}. "
                    "Try another search angle."
        ))

    # 理论上不会到这里（循环体在 iteration == max_iterations 时已经 return）。
    return {"answer": "", "results": _ranked_results(), "iterations": max_iterations,
            "tool_calls_made": tool_calls_made}


def _to_json(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)
