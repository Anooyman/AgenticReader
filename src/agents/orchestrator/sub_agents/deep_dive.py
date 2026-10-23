"""子 Agent：包装 AgenticReader 的 AnswerAgent，直接同进程调用（原
ai-research-pipeline 实现是通过 subprocess 调用独立 worker 脚本，因为
webapp 和 AgenticReader 当时在两个不同 venv 里；合并进同一个项目后不再
需要这层隔离，直接 await AnswerAgent(...).query(...) 即可）。

REFACTOR_REPORT §8.2：原实现每次提问都新建一个 AnswerAgent 并重读 registry，
是明显的热点。这里按 (doc_name, provider) 做有界 LRU 复用，省掉每次构造
DocumentRegistry + LLMBase 的成本。

复用安全性（已按 query()/graph 代码核对）：
- AnswerAgent.query() 每次都用 _build_initial_state 造一份全新的 AnswerState，
  tool_calls / tool_results / final_answer / is_complete / error / rewritten_query
  这些"跨查询可变态"全部活在 per-invoke 的 state dict 里、由图内节点原地读写，
  实例本身不累积这些结果 —— 因此同 doc 并发两问各自独立、互不污染。
- 实例级共享的只有 LLM 会话历史与 RetrievalAgent 池：会话历史用查询前 + 查询后
  各调一次 reset_history() 双向防脏（reset_history 已覆盖 answer 自身的
  tool_planning / rewrite_query_session / generate_answer 会话）；RetrievalAgent 池
  本就是实例自持的检索缓存，复用即收益。
- current_doc 是实例属性，但缓存 key 含 doc_name，同一实例的所有查询都指向同一
  doc_name，query() 里的赋值是幂等的，无并发竞态。
- 缓存 key 不含"文档存在"语义，复用的 DocumentRegistry 可能读到过期记录。查询
  返回 error、或检索全部失败（多半是文档已被删除 / 索引缺失）时剔除该缓存项，
  下次调用重建实例、重新走一遍 registry 校验。
"""
from collections import OrderedDict
from typing import Any, Dict

from src.agents.orchestrator.sub_agents.base import ProgressCallback, SubAgent
from src.config.settings import resolve_provider


# ==================== AnswerAgent 实例缓存（有界 LRU）====================
# 单事件循环内访问，无需加锁；超出容量淘汰最久未使用项。
_ANSWER_AGENT_CACHE: "OrderedDict[tuple, Any]" = OrderedDict()
_ANSWER_AGENT_CACHE_MAX = 32

# 供观测 / 测试：命中、未命中计数。
_CACHE_STATS = {"hits": 0, "misses": 0}


def _get_or_create_agent(doc_name: str, provider: str):
    """取缓存中的 AnswerAgent，未命中则构造并写入（含 LRU 淘汰）。"""
    key = (doc_name, provider)
    agent = _ANSWER_AGENT_CACHE.get(key)
    if agent is not None:
        _ANSWER_AGENT_CACHE.move_to_end(key)
        _CACHE_STATS["hits"] += 1
        return agent

    _CACHE_STATS["misses"] += 1
    # 延迟 import：保持 orchestrator.sub_agents 模块级不拖上 langgraph 依赖链。
    from src.agents.answer import AnswerAgent

    agent = AnswerAgent(doc_name=doc_name, provider=provider)
    _ANSWER_AGENT_CACHE[key] = agent
    _ANSWER_AGENT_CACHE.move_to_end(key)
    while len(_ANSWER_AGENT_CACHE) > _ANSWER_AGENT_CACHE_MAX:
        _ANSWER_AGENT_CACHE.popitem(last=False)
    return agent


def _evict_cached_agent(doc_name: str, provider: str) -> None:
    """剔除缓存项（文档被删 / 查询报错时），令下次调用重建以重走 registry 校验。"""
    _ANSWER_AGENT_CACHE.pop((doc_name, provider), None)


def _should_evict(result_state: Any) -> bool:
    """判定是否需要剔除缓存：state 报错，或启用的检索全部失败（多为文档已删除）。"""
    if not isinstance(result_state, dict):
        return True
    if result_state.get("error"):
        return True
    tool_results = result_state.get("tool_results") or []
    if tool_results and all(not tr.get("success") for tr in tool_results):
        return True
    return False


class DeepDiveAgent(SubAgent):
    name = "deep_dive_document"

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Ask a follow-up question against the FULL ORIGINAL TEXT of a specific "
                    "paper/article (identified by doc_name, typically obtained from a prior "
                    "search_memory hit). Use this when the memory abstract/summary doesn't "
                    "contain enough detail — e.g. exact formulas, algorithm steps, "
                    "experimental numbers, or any specifics beyond the high-level summary. "
                    "This is SLOWER than search_memory (it re-analyzes the original document), "
                    "so only call it when the summary genuinely falls short."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doc_name": {"type": "string", "description": "The AgenticReader doc_name to query (from a search_memory hit's source_id field)."},
                        "question": {"type": "string", "description": "The specific detailed question to ask against the original document."},
                    },
                    "required": ["doc_name", "question"],
                },
            },
        }

    async def invoke(self, on_progress: ProgressCallback = None, **kwargs) -> Dict[str, Any]:
        doc_name = kwargs["doc_name"]
        question = kwargs["question"]

        if on_progress:
            result = on_progress("deep_diving", f"正在深挖原文细节（{doc_name}）...")
            if result is not None:
                await result

        # provider 由 Orchestrator.ask 解析后经 tool 调用参数透传；直接
        # 实例化调用（无 provider kwarg）时 resolve_provider(None) 按
        # app_config.json → env → openai 回退。
        provider = resolve_provider(kwargs.get("provider"))

        try:
            agent = _get_or_create_agent(doc_name, provider)

            # 查询前重置：复用实例时防止上一次查询残留的会话历史串入本次。
            agent.reset_history()
            try:
                result_state = await agent.query(
                    user_query=question,
                    enabled_tools=["retrieve_documents"],
                    selected_docs=[doc_name],
                )
            finally:
                # 查询后重置：双向防脏，令实例回到干净态供下次复用。
                try:
                    agent.reset_history()
                except Exception:  # noqa: BLE001
                    pass

            if _should_evict(result_state):
                _evict_cached_agent(doc_name, provider)

            return {"doc_name": doc_name, "answer": result_state.get("final_answer", "")}
        except Exception as e:  # noqa: BLE001
            # 构造 / 查询整体抛错：剔除该缓存项，下次重建。
            _evict_cached_agent(doc_name, provider)
            return {"error": str(e), "doc_name": doc_name}
