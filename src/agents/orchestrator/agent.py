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
也是 src/agents/search/utils.py 里 SimpleMCPClient 已经
验证过的先例）。
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.orchestrator.prompts import EMPTY_ANSWER_FALLBACK, SYSTEM_PROMPT
from src.agents.orchestrator.sub_agents import ALWAYS_ON_TOOLS, SUB_AGENTS
from src.config.model_overrides import AGENT_MODEL_OVERRIDES
from src.config.settings import resolve_provider
from src.core.llm import LLMBase

logger = logging.getLogger(__name__)

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
# finalize 是一次"超预算时刻"的收尾 LLM 调用，给它一个远小于整轮预算的
# 硬超时——超时就直接交兜底答案，不再拖住墙钟。
FINALIZE_TIMEOUT = 120
# finalize 的收尾调用不必背着整轮的原始账：预算取 MAX_CONTEXT_CHARS
# 的一半——主流大窗口完全够用，小窗口 provider（Ollama 本地类）也
# 不会被 400 挡在门外。只裁内容，绝不删消息：tool_calls/ToolMessage
# 的配对关系动了就会撞 API 校验。
FINALIZE_CONTEXT_BUDGET = 60_000

ProgressCallback = Optional[Callable[[str, str], Awaitable[None]]]

# name -> schema 的映射用于按会话开关裁剪工具：SUB_AGENTS 是"有哪些工具"，
# enabled_tools 是"这次会话允许哪些"，两者取交集才是广告给模型的列表。
_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    name: agent.tool_schema() for name, agent in SUB_AGENTS.items()
}

# 裁历史时至少留下的最近消息条数——历史再长也不该把"刚说了什么"裁掉。
MIN_HISTORY_MESSAGES = 2

# 按条数预裁历史这件事由 session_manager 的 HISTORY_WINDOW_MESSAGES 承担，
# 本模块只保留字符预算那道兜底（见 _compose_messages）。


def _allowed_tool_names(enabled_tools: Optional[List[str]]) -> frozenset:
    """这次会话被允许使用的工具名集合——工具可见性的唯一判定处。

    规则刻意留得很窄，避免"两套开关口径"：
      * enabled_tools is None —— 调用方压根不管工具这回事，全开（与引入
        本参数之前的行为逐字一致，老调用点与 tests 不受影响）；
      * 给了值（哪怕是 []）—— 恒开工具 + 会话显式启用的那些，未启用的
        工具连 schema 都不出现，模型没法"顺手"调用它。
    前端那个「🌐 网络搜索」开关走的就是第二条：勾上才会把 search_web
    交给 Orchestrator。enabled_tools 里出现不认识的名字（例如 AnswerAgent
    那侧才有的 retrieve_documents）不报错也不放大权限——按未注册处理。
    """
    if enabled_tools is None:
        return frozenset(_TOOL_SCHEMAS)
    return frozenset(ALWAYS_ON_TOOLS) | (frozenset(enabled_tools) & frozenset(_TOOL_SCHEMAS))


def _advertised_tools(enabled_tools: Optional[List[str]]) -> List[Dict[str, Any]]:
    """按 _allowed_tool_names 把工具 schema 列表裁出来。"""
    allowed = _allowed_tool_names(enabled_tools)
    return [schema for name, schema in _TOOL_SCHEMAS.items() if name in allowed]


def _tool_result_message(tool_call_id: str, result: dict) -> ToolMessage:
    return ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id)


def _compose_messages(system_content: str,
                      history_msgs: List[Any],
                      question_message: Any) -> List[Any]:
    """组装本轮请求：system + 历史 + 本次提问，并且**首轮就落在预算内**。

    为什么把预算检查提到第一次调用之前：MAX_CONTEXT_CHARS 这道护栏原先只
    在"跑完一轮工具"之后才检查，于是一整份历史原封不动打给模型的情况从没
    被覆盖到过——长会话的第一问就可能超窗，用户看到的是模型端报 400 而不是
    "该做摘要了"。会话侧（session_manager 的窗口化 + 早期摘要）是第一道，
    这里是最后一道字符级兜底：从最老的历史开始丢，丢到装得下为止，并在
    system 里如实说明丢了几条——模型知道自己看到的史册不全，才不会假装
    记得被丢掉的那部分。

    保留线是最近 MIN_HISTORY_MESSAGES 条：历史再肥也不该把"刚聊了什么"裁没。
    """
    def _total(head: List[Any]) -> int:
        return _context_chars([SystemMessage(content=system_content)] + head + [question_message])

    head = list(history_msgs)
    dropped = 0
    while len(head) > MIN_HISTORY_MESSAGES and _total(head) > MAX_CONTEXT_CHARS:
        head.pop(0)
        dropped += 1

    if dropped:
        system_content = (
            f"{system_content}\n\n[Context budget] {dropped} earlier turn(s) were dropped "
            f"from this conversation history to fit the context window — do not claim to "
            f"remember their content."
        )
    return [SystemMessage(content=system_content)] + head + [question_message]


async def _safe_invoke(name: str, on_progress: ProgressCallback, args: dict,
                        default_namespaces: Optional[List[str]] = None,
                        provider: Optional[str] = None,
                        allowed: Optional[frozenset] = None) -> dict:
    """调用子 agent 并把任何意外异常降级为 {"error": ...} 结果。

    SubAgent 的契约是自己返回 error 字段而不抛异常，但这里的 try/except
    是最后一道防线——没有它，任何一个 agent 的未预期异常都会穿透
    asyncio.gather 把整轮问答一起炸掉。

    `allowed`：本次会话被启用的工具名集合。正常情况下模型只会看到启用的
    工具（schema 已按 enabled_tools 裁过），这里再挡一道是防模型凭空编造
    一个没广告过的工具名——光靠"unknown tool"那条分支分辨不了"不存在"和
    "本会话不该用"。

    `default_namespaces`：session 级别的默认检索范围。只对 search_memory
    生效，且只在 LLM 自己发起的 tool_call 没有显式传 namespace/namespaces
    时才补上——LLM 主动指定的 namespace 优先。"""
    agent = SUB_AGENTS.get(name)
    if agent is None:
        return {"error": f"unknown tool: {name}"}
    if allowed is not None and name not in allowed:
        return {"error": f"tool {name} is not enabled for this session"}
    if (name == "search_memory" and default_namespaces
            and not args.get("namespace") and not args.get("namespaces")):
        args = {**args, "namespaces": default_namespaces}
    if provider:
        # LLM 的 tool schema 里没有 provider 参数，注入不会与之冲突；
        # setdefault 语义——万一 args 带了 provider，以 args 为准。
        args = {**args, "provider": args.get("provider") or provider}
    try:
        return await agent.invoke(on_progress=on_progress, **args)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{name} 执行异常: {e}"}


async def _run_tool_calls(tool_calls, on_progress: ProgressCallback,
                           default_namespaces: Optional[List[str]] = None,
                           provider: Optional[str] = None,
                           allowed: Optional[frozenset] = None):
    """并行执行 LLM 在某一轮里发起的全部 tool_calls（不逐个 await）。

    第三个返回值是本轮各子 agent 带回的检索命中（search_memory 的
    hits）——原样取出交给 ask() 去重，UI 靠它渲染"提及论文"条目，
    不必等模型自己在正文里写出链接。"""
    async def _run_one(tool_call):
        name = tool_call["name"]
        args = tool_call.get("args") or {}
        return name, await _safe_invoke(name, on_progress, args, default_namespaces,
                                        provider, allowed)

    outcomes = await asyncio.gather(*[_run_one(tc) for tc in tool_calls])

    tool_messages = [
        _tool_result_message(tc["id"], result)
        for tc, (_, result) in zip(tool_calls, outcomes)
    ]
    sources_used = [name for name, _ in outcomes]
    round_hits: List[Dict[str, Any]] = []
    for _, result in outcomes:
        if isinstance(result, dict):
            round_hits.extend(h for h in (result.get("hits") or []) if isinstance(h, dict))
    return tool_messages, sources_used, round_hits


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


def _compact_messages_for_finalize(messages: List[Any],
                                   budget: int = FINALIZE_CONTEXT_BUDGET,
                                   keep_tail: int = 12) -> List[Any]:
    """finalize 前的消息瘦身——120k 护栏只在迭代边界检查，而 finalize 恰恰
    是在"刚超预算"的时刻触发：原样发出去，在大窗口上只是偏贵，在窗口小
    的 provider 上直接 400，被兜底 except 接住就只剩空答案——明明全有
    上下文，却交给用户一句"答不上来"。

    策略不删任何一条消息（tool_calls 配对必须原样），只做三件事：
      头：首条 SystemMessage + 首条 HumanMessage 原样（系统提示与原始问题）；
      尾：最近 keep_tail 条原样（本轮工具刚吐的东西都在里面）；
      中部：其余内容换成标注了原长度的占位 stub。
    裁完仍超预算，就把尾部的工具结果也截到 4k——那通常才是体积大头。
    """
    if _context_chars(messages) <= budget:
        return messages
    keep_idx = set()
    i_sys = next((i for i, m in enumerate(messages) if isinstance(m, SystemMessage)), None)
    i_human = next((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), None)
    if i_sys is not None:
        keep_idx.add(i_sys)
    if i_human is not None:
        keep_idx.add(i_human)
    tail_start = max(len(messages) - keep_tail, 0)

    out: List[Any] = []
    for i, m in enumerate(messages):
        if i in keep_idx or i >= tail_start:
            out.append(m)
            continue
        original = str(getattr(m, "content", "") or "")
        stub = (f"[中段消息已略去——{type(m).__name__}，原 {len(original)} 字，"
                "内容见尾部的本轮结果]")
        try:
            out.append(m.model_copy(update={"content": stub}))
        except Exception:  # noqa: BLE001 — 复制不动就留着原样，总比丢了强
            out.append(m)

    if _context_chars(out) > budget:
        for j, m in enumerate(out):
            if not isinstance(m, ToolMessage):
                continue
            body = str(m.content or "")
            if len(body) > 4000:
                try:
                    out[j] = m.model_copy(update={"content": body[:4000] + "…[截断]"})
                except Exception:  # noqa: BLE001
                    pass
            if _context_chars(out) <= budget:
                break
    return out


async def ask(
    question: str,
    doc_name: str = None,
    namespaces: Optional[List[str]] = None,
    history: Optional[List[Dict[str, str]]] = None,
    on_progress: ProgressCallback = None,
    provider: Optional[str] = None,
    enabled_tools: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """跑一次完整的 Orchestrator 编排，返回
    {"answer": str, "sources_used": [子agent name, ...],
     "memory_hits": [本次检索命中的记忆条目, ...], "stop_reason": str}。

    `doc_name`：UI 层已知的、这次提问明确关联的文档（例如单文档对话模式，
    或从 report 页面"针对这篇继续提问"跳转过来）。已知时只是作为上下文
    提示写进首条用户消息，让 LLM 知道有一个绑定文档可以 deep_dive_document——
    是否真的调用、要不要先/也查 search_memory，完全由 LLM 判断，不再有
    代码强制注入的首轮 tool_call。

    `namespaces`：用户在这个 session 上设置的记忆检索范围（session 级
    memory_namespaces，经 chat_service 透传）。省略/空不是"全部"：由
    src/memory/gateway 补成缺省自库白名单（D-B：ai-research +
    webapp-chat）；显式列表按其子集生效，"*" 才表示全部 namespace。

    `history`：本 session 此前的对话消息（[{"role": "user"|"assistant"|
    "system", "content": ...}, ...]，不含本次 question）。省略表示全新
    对话。超长历史在这里还有一道按字符预算的裁剪兜底——会话侧
    （session_manager）已经做了窗口化 + 早期摘要，这里防的是摘要块本身
    太肥、或者调用方绕过了会话层直接灌一整份历史。

    `provider`：显式指定则原样使用；省略走 settings.resolve_provider(None)
    （app_config.json → env PROVIDER → "openai"）。解析结果同时下发给
    deep_dive_document / search_memory 子 agent，保证一次提问里编排 LLM、
    文档深挖、记忆检索用同一个 provider。

    `enabled_tools`：这个会话这次允许用的工具名列表（前端工具开关经
    chat_service 透传）。None = 调用方不管工具，全开；给了值就按
    恒开工具 ∪ 显式启用来广告工具列表，见 _advertised_tools。
    """
    resolved_provider = resolve_provider(provider)
    model_name = AGENT_MODEL_OVERRIDES.get("Orchestrator")
    llm = LLMBase(provider=resolved_provider, model=model_name)

    tools = _advertised_tools(enabled_tools)
    allowed = _allowed_tool_names(enabled_tools)

    # 历史段先单独装配，装配与预算检查一起交给 _compose_messages。
    history_msgs: List[Any] = []
    for msg in history or []:
        content = msg.get("content") or ""
        role = msg.get("role")
        if role == "user":
            history_msgs.append(HumanMessage(content=content))
        elif role == "system":
            history_msgs.append(SystemMessage(content=content))
        else:
            history_msgs.append(AIMessage(content=content))

    question_content = question
    if "Current date" not in question:
        try:
            local_now = datetime.now().astimezone()
            tz_abbr = local_now.tzname() or ""
            date_line = f"[Current date: {local_now:%Y-%m-%d}]"
            if tz_abbr:
                date_line = f"{date_line} ({tz_abbr})"
            question_content = f"{date_line}\n{question_content}"
        except Exception:  # noqa: BLE001 - date context is best-effort, never break a turn
            pass
    if doc_name:
        question_content = (
            f"[This conversation is bound to doc_name=\"{doc_name}\" — you may call "
            f"deep_dive_document with this doc_name if needed.]\n{question}"
        )
    messages = _compose_messages(SYSTEM_PROMPT, history_msgs,
                                 HumanMessage(content=question_content))

    sources_used: List[str] = []
    # 本轮起各轮 search_memory 带回的命中账本——UI 的"提及论文可下载"
    # 条目靠它，不依赖模型在正文里是否写出链接。
    memory_hits: List[Dict[str, Any]] = []
    _seen_hit_keys: set = set()

    def _note_hits(hits: List[Dict[str, Any]]) -> None:
        for h in hits:
            abstract = (h.get("abstract") or "").strip()
            key = h.get("id") or (h.get("source_id", ""), abstract[:80])
            if not key or key in _seen_hit_keys:
                continue
            _seen_hit_keys.add(key)
            if len(memory_hits) < 20:
                entry = {k: h[k] for k in ("source_id", "source_type", "url", "doc_name") if h.get(k)}
                entry["abstract"] = abstract[:160]
                memory_hits.append(entry)

    async def finalize(reason: str) -> Dict[str, Any]:
        """强制关闭工具调用，逼模型基于已有信息给出结论。"""
        model = llm.chat_model  # 不 bind 任何 tool，模型物理上无法再发起 tool_call
        # finalize 自己也要有超时：它跑在"已经超了预算"的时刻，一次没有
        # 上限的 ainvoke 能把 900s 墙钟变成无限——收尾调用不该比它收尾的
        # 整轮还贵。
        try:
            response = await asyncio.wait_for(
                model.ainvoke(_compact_messages_for_finalize(messages)),
                timeout=FINALIZE_TIMEOUT)
        except asyncio.TimeoutError:
            response = None
        except Exception as e:  # noqa: BLE001 — finalize 的职责是"无论如何交出答案"
            # 最常见的是历史形状不合 API 校验（AIMessage.tool_calls 后面缺
            # 配对的 ToolMessage）——收尾调用不该把整次提问带崩。
            logger.warning("finalize 的收尾调用失败，改用兜底答案：%s: %s",
                           type(e).__name__, e)
            response = None
        answer = ((response.content or "").strip() if response is not None else "")
        if not answer:
            answer = EMPTY_ANSWER_FALLBACK
        return {"answer": answer, "sources_used": sources_used,
                "memory_hits": memory_hits, "stop_reason": reason}

    consecutive_error_rounds = 0
    deadline = time.monotonic() + OVERALL_DEADLINE

    for _ in range(MAX_ITERATIONS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return await finalize("deadline")

        model = llm.get_chat_model_with_tools(tools=tools)
        # 墙钟的约束对象是所有在途的 await，不只是迭代开头那一瞬：以前
        # 只在循环顶部查 deadline，一次超过剩余预算的模型调用或工具轮
        # （deep_dive 单文档曾配到 1200s > 900s 整轮）能把护栏变成摆设。
        try:
            response = await asyncio.wait_for(model.ainvoke(messages), timeout=remaining)
        except asyncio.TimeoutError:
            return await finalize("deadline")

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            answer = (response.content or "").strip()
            return {"answer": answer or EMPTY_ANSWER_FALLBACK,
                    "sources_used": sources_used,
                    "memory_hits": memory_hits, "stop_reason": "answered"}

        messages.append(response)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return await finalize("deadline")
        try:
            tool_messages, round_sources, round_hits = await asyncio.wait_for(
                _run_tool_calls(
                    tool_calls, on_progress, namespaces, provider=resolved_provider,
                    allowed=allowed),
                timeout=remaining)
        except asyncio.TimeoutError:
            # 工具轮超掉了剩余预算：给这轮每个 tool_call 补一条超时观测，
            # 否则 finalize 的对话历史里会留着"有 tool_calls 没响应"的
            # 非法形状，收尾调用反而先撞 API 校验。
            for tc in tool_calls:
                messages.append(ToolMessage(
                    content="工具调用超时（已超出本轮时间预算）。",
                    tool_call_id=tc.get("id") or ""))
            # 已收集到的 sources/memory_hits 照常带出去。
            return await finalize("deadline")
        messages.extend(tool_messages)
        sources_used.extend(round_sources)
        _note_hits(round_hits)

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
