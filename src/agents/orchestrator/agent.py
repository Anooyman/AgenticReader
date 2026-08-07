"""主 Agent（Orchestrator）——唯一面向用户、唯一持有对话历史的角色。

改自 ai-research-pipeline 的 webapp/agents/orchestrator.py。与最初搬运版本
的区别：不再有"第一轮固定并行调用 search_memory（+已知 doc_name 时的
deep_dive_document）"的硬编码分支。是否检索 memory、是否深挖原文，从第一轮
开始就完全交给 LLM 自主判断（ReAct），doc_name 已知这件事只是作为上下文
提示写进首条用户消息，不再强制注入 tool_call——精确的文档细节提问可以直接
deep_dive_document 跳过 memory 检索，省一次开销；模糊回忆型提问模型会自己
选 search_memory。

任意一轮如果同时产生多个 tool_calls，一律用 asyncio.gather 并行执行，不
逐个 await。工具调用格式使用 AgenticReader 已有的 LLMBase + LangChain
bind_tools 惯例（与 src/memory/search.py 的 agentic_search 用同一套模式，
也是 src/services/mcp_client.py 里 MCPClient._process_with_tools 已经
验证过的先例）。
"""
import asyncio
import json
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.orchestrator.prompts import EMPTY_ANSWER_FALLBACK, SYSTEM_PROMPT
from src.agents.orchestrator.sub_agents import SUB_AGENTS
from src.config.model_overrides import AGENT_MODEL_OVERRIDES
from src.core.llm import LLMBase

# 反复调用工具往往不是死循环，而是真的没检索到关键信息、换个说法再试一次，
# 这是合理行为，所以轮次给得宽松。真正需要防的是下面两件事：上下文无限
# 膨胀、以及工具一直报错时还傻等满轮次。
MAX_ITERATIONS = 15

# 累计上下文超过这个字符数就强制收尾——十几轮堆下来会把 prompt 撑爆。
MAX_CONTEXT_CHARS = 120_000

# 连续这么多轮工具调用全部失败就提前收尾。
MAX_CONSECUTIVE_TOOL_ERRORS = 2

# 整轮问答的墙钟预算，到点就用已有信息强制收尾。
OVERALL_DEADLINE = 900

ProgressCallback = Optional[Callable[[str, str], Awaitable[None]]]

_TOOLS = [agent.tool_schema() for agent in SUB_AGENTS.values()]


def _tool_result_message(tool_call_id: str, result: dict) -> ToolMessage:
    return ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id)


async def _maybe_await(value):
    if value is not None:
        await value


async def _safe_invoke(name: str, on_progress: ProgressCallback, args: dict,
                        default_namespaces: Optional[List[str]] = None) -> dict:
    """调用子 agent 并把任何意外异常降级为 {"error": ...} 结果。

    SubAgent 的契约是自己返回 error 字段而不抛异常，但这里的 try/except
    是最后一道防线——没有它，任何一个 agent 的未预期异常都会穿透
    asyncio.gather 把整轮问答一起炸掉。

    `default_namespaces`：session 级别的默认检索范围。只对 search_memory
    生效，且只在 LLM 自己发起的 tool_call 没有显式传 namespace/namespaces
    时才补上——LLM 主动指定的 namespace 优先。"""
    agent = SUB_AGENTS.get(name)
    if agent is None:
        return {"error": f"unknown tool: {name}"}
    if (name == "search_memory" and default_namespaces
            and not args.get("namespace") and not args.get("namespaces")):
        args = {**args, "namespaces": default_namespaces}
    try:
        return await agent.invoke(on_progress=on_progress, **args)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{name} 执行异常: {e}"}


async def _run_tool_calls(tool_calls, on_progress: ProgressCallback,
                           default_namespaces: Optional[List[str]] = None):
    """并行执行 LLM 在某一轮里发起的全部 tool_calls（不逐个 await）。"""
    async def _run_one(tool_call):
        name = tool_call["name"]
        args = tool_call.get("args") or {}
        return name, await _safe_invoke(name, on_progress, args, default_namespaces)

    outcomes = await asyncio.gather(*[_run_one(tc) for tc in tool_calls])

    tool_messages = [
        _tool_result_message(tc["id"], result)
        for tc, (_, result) in zip(tool_calls, outcomes)
    ]
    sources_used = [name for name, _ in outcomes]
    return tool_messages, sources_used


def _all_errored(tool_messages: List[ToolMessage]) -> bool:
    return all("\"error\":" in m.content for m in tool_messages)


def _context_chars(messages: List[Any]) -> int:
    total = 0
    for m in messages:
        content = getattr(m, "content", "") or ""
        total += len(str(content))
        tool_calls = getattr(m, "tool_calls", None)
        if tool_calls:
            total += len(json.dumps(tool_calls, ensure_ascii=False))
    return total


async def ask(
    question: str,
    doc_name: str = None,
    namespaces: Optional[List[str]] = None,
    history: Optional[List[Dict[str, str]]] = None,
    on_progress: ProgressCallback = None,
) -> Dict[str, Any]:
    """跑一次完整的 Orchestrator 编排，返回
    {"answer": str, "sources_used": [子agent name, ...], "stop_reason": str}。

    `doc_name`：UI 层已知的、这次提问明确关联的文档（例如单文档对话模式，
    或从 report 页面"针对这篇继续提问"跳转过来）。已知时只是作为上下文
    提示写进首条用户消息，让 LLM 知道有一个绑定文档可以 deep_dive_document——
    是否真的调用、要不要先/也查 search_memory，完全由 LLM 判断，不再有
    代码强制注入的首轮 tool_call。

    `namespaces`：用户创建这个 session 时勾选的默认记忆检索范围。省略/空
    表示不限定，检索全部 namespace。

    `history`：本 session 此前的对话消息（[{"role": "user"|"assistant",
    "content": ...}, ...]，不含本次 question）。省略表示全新对话。
    """
    model_name = AGENT_MODEL_OVERRIDES.get("Orchestrator")
    llm = LLMBase(provider="openai", model=model_name)

    messages: List[Any] = [SystemMessage(content=SYSTEM_PROMPT)]
    for msg in history or []:
        messages.append(HumanMessage(content=msg["content"]) if msg["role"] == "user"
                        else AIMessage(content=msg["content"]))

    question_content = question
    if doc_name:
        question_content = (
            f"[This conversation is bound to doc_name=\"{doc_name}\" — you may call "
            f"deep_dive_document with this doc_name if needed.]\n{question}"
        )
    messages.append(HumanMessage(content=question_content))
    sources_used: List[str] = []

    async def finalize(reason: str) -> Dict[str, Any]:
        """强制关闭工具调用，逼模型基于已有信息给出结论。"""
        model = llm.chat_model  # 不 bind 任何 tool，模型物理上无法再发起 tool_call
        response = await model.ainvoke(messages)
        answer = (response.content or "").strip()
        if not answer:
            answer = EMPTY_ANSWER_FALLBACK
        return {"answer": answer, "sources_used": sources_used, "stop_reason": reason}

    consecutive_error_rounds = 0
    deadline = time.monotonic() + OVERALL_DEADLINE

    for _ in range(MAX_ITERATIONS):
        if time.monotonic() > deadline:
            return await finalize("deadline")

        model = llm.get_chat_model_with_tools(tools=_TOOLS)
        response = await model.ainvoke(messages)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            answer = (response.content or "").strip()
            return {"answer": answer or EMPTY_ANSWER_FALLBACK,
                    "sources_used": sources_used, "stop_reason": "answered"}

        messages.append(response)

        tool_messages, round_sources = await _run_tool_calls(tool_calls, on_progress, namespaces)
        messages.extend(tool_messages)
        sources_used.extend(round_sources)

        # 子 agent 失败时返回的是 {"error": ...}，模型看到的只是"没查到"，
        # 会换个措辞重试——但如果是超时/崩溃这类系统性故障，重试多少次都
        # 一样，只会白白烧完轮次然后交出一个空答案。整轮全错就计数，连续
        # 若干轮全错直接收尾，并如实告诉模型这是工具故障而不是查无此物。
        if _all_errored(tool_messages):
            consecutive_error_rounds += 1
            if consecutive_error_rounds >= MAX_CONSECUTIVE_TOOL_ERRORS:
                messages.append(HumanMessage(
                    content="检索工具连续多轮失败（超时或异常），不是没有相关内容。"
                            "请基于已有信息作答，并明确告诉用户这次检索没能正常完成。",
                ))
                return await finalize("tool_errors")
        else:
            consecutive_error_rounds = 0

        # 上下文膨胀到一定程度就收手：再多轮既贵又没用。
        if _context_chars(messages) > MAX_CONTEXT_CHARS:
            return await finalize("context_limit")

    return await finalize("max_iterations")
