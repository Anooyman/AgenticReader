"""子 Agent：包装 AgenticReader 的 SearchAgent（网络搜索 / URL 分析），
同进程直接 await 调用——与 deep_dive_document 包装 AnswerAgent 的做法一致。

这条链路的由来：SearchAgent 是五个 Agent 里唯一够不到 UI 的那个。CLI 可以
直接 `main.py` 走 [w] 模式，AnswerAgent 也有 `search_web` 工具，但 UI 聊天
走的是 Orchestrator，而 Orchestrator 的 SUB_AGENTS 里只有 search_memory 和
deep_dive_document——前端那个「🌐 网络搜索」开关点下去只是把 `search_web`
记进会话的 enabled_tools，模型端从来收不到这个工具。这里补上这条线。

工具可见性由 Orchestrator 按 enabled_tools 做 gating（见
orchestrator/agent.py 的 `_tool_names_allowed`）：本 agent 注册进 SUB_AGENTS，
但**只有会话启用网络搜索时才被广告给模型**。所以 agent 自己不读
enabled_tools——两处读就有两套口径。

实例复用：SearchAgent 每次 `search()` 收尾都会
`utils.cleanup_mcp_clients()` 把 MCP 连接关干净（见 utils.py:212-222 的
clear），实例不跨调用累积连接状态，因此可以按 provider 缓存复用，省掉每次
重建 graph 与 provider 解析的开销——和 deep_dive 复用 AnswerAgent 同理。
缓存 key 只有 provider：SearchAgent 无 doc 维度状态。
"""
from typing import Any, Dict, List

from src.agents.orchestrator.sub_agents.base import ProgressCallback, SubAgent
from src.config.settings import resolve_provider

# provider -> SearchAgent 实例。provider 一共四个，上限留 8 足矣（留一点
# 显式传参带进来的变体余量）。
_SEARCH_AGENTS: "Dict[str, Any]" = {}
_SEARCH_AGENTS_MAX = 8


def _get_search_agent(provider: str):
    """按 provider 取/建 SearchAgent（缓存 miss 才 import，保持 sub_agents
    模块级不拖 langgraph 依赖链）。"""
    agent = _SEARCH_AGENTS.get(provider)
    if agent is None:
        # 延迟 import：与 deep_dive 同一套理由——别在 import orchestrator 包时
        # 就把整条 langgraph 链拉起来。
        from src.agents.search import SearchAgent

        agent = SearchAgent(provider=provider)
        _SEARCH_AGENTS[provider] = agent
        if len(_SEARCH_AGENTS) > _SEARCH_AGENTS_MAX:
            # dict 保序，淘汰最早那个（等价 FIFO，够用且无锁竞争——单事件循环）。
            _SEARCH_AGENTS.pop(next(iter(_SEARCH_AGENTS)), None)
    return agent


class WebSearchAgent(SubAgent):
    name = "search_web"

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Search the live web for information that is NOT already in the user's "
                    "memory or indexed documents — current events, release notes, pricing, "
                    "anything time-sensitive, or a specific URL the user pasted for analysis. "
                    "Do NOT use it for questions the research memory or an indexed paper can "
                    "answer (call search_memory / deep_dive_document for those). Returns a "
                    "synthesized answer plus the source URLs it was built from. "
                    "Note: an analyzed page that is long may be indexed automatically, which "
                    "takes longer than a plain search."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The question or search terms to look up online.",
                        },
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Optional. Explicit URLs to fetch and analyze instead of "
                                "running a search (e.g. a link the user just pasted). Omit "
                                "for a normal keyword search."
                            ),
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    async def invoke(self, on_progress: ProgressCallback = None, **kwargs) -> Dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return {"error": "search_web 缺少 query 参数"}

        urls = kwargs.get("urls") or kwargs.get("target_urls") or []
        if isinstance(urls, str):
            urls = [urls]
        # 先滤掉 None / 空串再转字符串：模型很爱在数组里塞 null，而
        # str(None) == "None" 会溜过非空判断、被 SearchAgent 当成一个真实
        # 目标 URL 去抓。
        urls = [u for u in (str(x).strip() for x in urls if x is not None and str(x).strip()) if u]

        if on_progress:
            detail = (
                f"正在分析 {len(urls)} 个链接..." if urls else "正在搜索网络..."
            )
            result = on_progress("searching_web", detail)
            if result is not None:
                await result

        # provider 与 ask() 同源（编排侧解析后透传），这里只做缺省补全。
        provider = resolve_provider(kwargs.get("provider"))

        try:
            agent = _get_search_agent(provider)
            result = await agent.search(query=query, target_urls=urls or None)
        except Exception as e:  # noqa: BLE001 —— 契约：失败返 error，不抛
            return {"error": f"search_web 执行失败: {e}"}

        if result.get("error"):
            # SearchAgent 失败时也会给出 answer=""，但把原因留在 error 键上，
            # 编排模型才分得清"没搜到"和"没搜成"。
            return {"error": result["error"]}

        sources: List[str] = [s for s in (result.get("sources") or []) if isinstance(s, str) and s]
        payload: Dict[str, Any] = {
            "answer": result.get("answer", ""),
            "sources": sources,
            "use_case": result.get("use_case", ""),
        }
        # 长内容自动索引这条副作用要能让模型知道，否则它只会觉得这一轮特别慢。
        warnings = [w for w in (result.get("warnings") or []) if w]
        if warnings:
            payload["warnings"] = warnings
        if result.get("processing_strategy"):
            payload["processing_strategy"] = result["processing_strategy"]

        if not payload["answer"] and not sources:
            return {"error": "search_web 没有返回任何内容（可能是搜索与抓取都无结果）"}
        return payload
