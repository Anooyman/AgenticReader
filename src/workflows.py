"""
Workflow路由器

支持新旧架构共存，根据场景选择合适的工作流
"""

from typing import Literal, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class WorkflowRouter:
    """
    工作流路由器

    支持两种模式：
    - simple: 使用Answer/Retrieval/Indexing Agent（适合直接问答）
    - complex: 使用PlanAgent/ExecutorAgent（适合复杂任务）

    用法：
        router = WorkflowRouter()

        # 简单问答
        answer = await router.route(
            query="这个文档讲了什么？",
            mode="simple"
        )

        # 复杂任务
        result = await router.route(
            query="分析这三个文档的共同点",
            mode="complex"
        )
    """

    def __init__(self):
        self.answer_agent = None
        self.plan_agent = None

    async def route(
        self,
        query: str,
        mode: Literal["simple", "complex"] = "simple",
        **kwargs
    ) -> str:
        """
        根据模式选择工作流

        Args:
            query: 用户查询
            mode: 工作流模式
                - simple: Answer Agent模式（快速、直接）
                - complex: Plan Agent模式（复杂、多步骤）
            **kwargs: 其他参数
                - current_doc: 当前文档名
                - doc_tags: 文档标签
                - conversation_history: 对话历史

        Returns:
            最终回答文本
        """
        logger.info(f"🔀 [Router] 路由查询: mode={mode}, query='{query[:50]}...'")

        if mode == "simple":
            return await self._run_answer_agent(query, **kwargs)
        elif mode == "complex":
            return await self._run_plan_agent(query, **kwargs)
        else:
            raise ValueError(f"不支持的模式: {mode}")

    async def _run_answer_agent(self, query: str, **kwargs) -> str:
        """
        运行Answer Agent工作流（新架构）

        Args:
            query: 用户查询
            **kwargs: 可选参数
                - current_doc: str
                - doc_tags: List[str]
                - conversation_history: List[Dict]

        Returns:
            最终回答
        """
        logger.info(f"🤖 [Router] 使用Answer Agent（新架构）")

        try:
            # 延迟加载Answer Agent
            if self.answer_agent is None:
                from src.agents.answer import AnswerAgent
                self.answer_agent = AnswerAgent()
                logger.info("✅ Answer Agent已加载")

            # 调用Answer Agent
            result = await self.answer_agent.graph.ainvoke({
                "user_query": query,
                "current_doc": kwargs.get("current_doc"),
                "doc_tags": kwargs.get("doc_tags"),
                "conversation_history": kwargs.get("conversation_history"),
                # 初始化必需字段
                "needs_retrieval": False,
                "is_complete": False
            })

            answer = result.get("final_answer", "抱歉，无法生成回答。")

            logger.info(f"✅ [Router] Answer Agent完成")

            return answer

        except Exception as e:
            logger.error(f"❌ [Router] Answer Agent失败: {e}")
            return f"抱歉，处理查询时出现错误：{str(e)}"

    async def _run_plan_agent(self, query: str, **kwargs) -> str:
        """
        运行Plan Agent工作流（旧架构）

        Args:
            query: 用户查询
            **kwargs: 可选参数

        Returns:
            最终回答
        """
        logger.info(f"🧩 [Router] 使用Plan Agent（旧架构）")

        try:
            # 延迟加载Plan Agent
            if self.plan_agent is None:
                from src.chat.chat import PlanAgent
                self.plan_agent = PlanAgent()
                logger.info("✅ Plan Agent已加载")

            # 调用Plan Agent
            result = await self.plan_agent.graph.ainvoke({
                "question": query,
                **kwargs
            })

            answer = result.get("final_answer", "抱歉，无法生成回答。")

            logger.info(f"✅ [Router] Plan Agent完成")

            return answer

        except Exception as e:
            logger.error(f"❌ [Router] Plan Agent失败: {e}")
            return f"抱歉，处理查询时出现错误：{str(e)}"

    async def index_document(
        self,
        doc_name: str,
        doc_path: str,
        doc_type: Literal["pdf", "url"],
        manual_tags: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        索引文档（使用Indexing Agent）

        Args:
            doc_name: 文档名称
            doc_path: 文档路径
            doc_type: 文档类型
            manual_tags: 手动指定的标签

        Returns:
            索引结果字典
        """
        logger.info(f"📑 [Router] 索引文档: {doc_name}")

        try:
            from src.agents.indexing import IndexingAgent

            # 创建Indexing Agent
            indexing_agent = IndexingAgent()

            # 调用索引流程
            result = await indexing_agent.graph.ainvoke({
                "doc_name": doc_name,
                "doc_path": doc_path,
                "doc_type": doc_type,
                "manual_tags": manual_tags,
                # 初始化状态
                "status": "pending"
            })

            logger.info(f"✅ [Router] 文档索引完成: {result.get('doc_id')}")

            return {
                "success": result.get("status") == "completed",
                "doc_id": result.get("doc_id"),
                "index_path": result.get("index_path"),
                "tags": result.get("tags"),
                "brief_summary": result.get("brief_summary"),
                "error": result.get("error")
            }

        except Exception as e:
            logger.error(f"❌ [Router] 文档索引失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def auto_select_mode(self, query: str) -> Literal["simple", "complex"]:
        """
        自动选择工作流模式（实验性功能）

        基于查询复杂度自动选择simple或complex模式

        Args:
            query: 用户查询

        Returns:
            推荐的模式
        """
        # 简单策略：基于关键词判断
        complex_keywords = [
            "分析", "比较", "总结多个", "跨文档", "综合",
            "对比", "整理", "汇总", "多步骤"
        ]

        query_lower = query.lower()

        for keyword in complex_keywords:
            if keyword in query_lower:
                logger.info(f"🎯 [Router] 自动选择: complex（检测到关键词: {keyword}）")
                return "complex"

        logger.info(f"🎯 [Router] 自动选择: simple")
        return "simple"
