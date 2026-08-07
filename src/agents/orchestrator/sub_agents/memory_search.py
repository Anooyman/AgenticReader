"""子 Agent：包装 src.memory.search.agentic_search()，直接同进程调用（原
ai-research-pipeline 实现因为 LLM-Memory 和 webapp 在两个不同 venv 里，
只能 subprocess 调用独立 worker 脚本；合并进 AgenticReader 后
src.memory.search 与本项目其余代码同进程运行，直接 await 调用即可）。

多 namespace 支持：agentic_search 本身只接受一个 namespace 列表参数
（VectorStore._where 天然支持 `namespace IN (...)`），不需要像原实现那样
对每个 namespace 分别起一次调用再合并——这是搬运时的简化：原来的"多 worker
subprocess 并行 + 合并"存在是因为 LLM-Memory 的 VectorStore 只支持单个
namespace 精确匹配；本项目重新实现的 VectorStore（见 src/memory/
vector_store.py）在 _where() 里已经原生支持 namespace 列表，一次调用即可。
"""
from typing import Any, Dict

from src.agents.orchestrator.sub_agents.base import ProgressCallback, SubAgent


class MemorySearchAgent(SubAgent):
    name = "search_memory"

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Search the user's persistent memory (past-ingested paper/article "
                    "summaries and prior conversation notes) for anything semantically "
                    "relevant to the user's question. Use this FIRST for any question that "
                    "references remembered content, even vaguely (e.g. 'that paper about X', "
                    "'what did we discuss about Y'). Searches across ALL memory by default "
                    "(namespace omitted) — only pass namespace if the user's question is "
                    "explicitly scoped to one kind of content. Returns a synthesized answer "
                    "plus a list of hits, each optionally carrying a source_id you can pass to "
                    "deep_dive_document for details beyond the stored summary."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural-language question to search memory with."},
                        "namespace": {
                            "type": "string",
                            "description": (
                                "Optional. Restrict the search to one namespace (e.g. "
                                "'ai-research' for paper/article summaries, 'webapp-chat' for "
                                "prior conversation notes). Omit to search across all memory."
                            ),
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    async def invoke(self, on_progress: ProgressCallback = None, **kwargs) -> Dict[str, Any]:
        query = kwargs["query"]
        # namespaces（list，来自 session 创建时勾选的默认范围）优先于
        # namespace（单个字符串，来自 LLM 自主 tool_call 的显式指定）。
        namespaces = kwargs.get("namespaces")
        namespace = kwargs.get("namespace")
        effective_namespace = namespaces or ([namespace] if namespace else None)

        if on_progress:
            result = on_progress("searching_memory", "正在检索相关记忆...")
            if result is not None:
                await result

        try:
            from src.memory.search import agentic_search

            result = await agentic_search(query, namespace=effective_namespace, provider="openai")
            return {"answer": result.get("answer", ""), "hits": self._shape_hits(result.get("results", []))}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    @staticmethod
    def _shape_hits(results: list) -> list:
        hits = []
        for row in results:
            hit = {
                "source_id": row.get("source_id", ""),
                "source_type": row.get("source_type", ""),
                "abstract": row.get("abstract", ""),
                "score": row.get("score", 0),
            }
            if row.get("source_type") == "ai_research" and row.get("source_id"):
                # source_id 本身就是 doc_name（见 src/memory/adapters/ai_research.py
                # 的约定），不需要像原实现那样反查摘要文件才能拿到 doc_name。
                hit["doc_name"] = row["source_id"]
            hits.append(hit)
        return hits
