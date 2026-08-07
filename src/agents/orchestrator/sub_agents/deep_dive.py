"""子 Agent：包装 AgenticReader 的 AnswerAgent，直接同进程调用（原
ai-research-pipeline 实现是通过 subprocess 调用独立 worker 脚本，因为
webapp 和 AgenticReader 当时在两个不同 venv 里；合并进同一个项目后不再
需要这层隔离，直接 await AnswerAgent(...).query(...) 即可）。
"""
from typing import Any, Dict

from src.agents.orchestrator.sub_agents.base import ProgressCallback, SubAgent


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

        try:
            from src.agents.answer import AnswerAgent

            agent = AnswerAgent(doc_name=doc_name, provider="openai")
            result_state = await agent.query(
                user_query=question,
                enabled_tools=["retrieve_documents"],
                selected_docs=[doc_name],
            )
            agent.reset_history()
            return {"doc_name": doc_name, "answer": result_state.get("final_answer", "")}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e), "doc_name": doc_name}
