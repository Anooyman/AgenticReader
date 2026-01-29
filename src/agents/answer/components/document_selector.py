"""
文档选择器 - 基于向量检索的智能文档选择

使用元数据向量数据库进行语义检索，自动选择与查询相关的文档
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class DocumentSelector:
    """文档选择器 - 智能筛选相关文档"""

    def __init__(self, llm_client, registry):
        """
        Args:
            llm_client: LLM客户端实例
            registry: DocumentRegistry实例
        """
        self.llm = llm_client
        self.registry = registry
        self.metadata_db = None
        self._initialize_metadata_db()

    def _initialize_metadata_db(self):
        """初始化元数据向量数据库"""
        try:
            from src.core.vector_db.metadata_db import MetadataVectorDB
            self.metadata_db = MetadataVectorDB()
            logger.info(f"✅ [Selector] 元数据向量数据库初始化成功")
        except Exception as e:
            logger.error(f"❌ [Selector] 元数据向量数据库初始化失败: {e}")
            self.metadata_db = None

    async def select_relevant_documents(
        self,
        query: str,
        max_docs: int = 5
    ) -> List[Dict[str, Any]]:
        """
        智能选择相关文档

        Args:
            query: 原始查询
            max_docs: 最多返回文档数

        Returns:
        [
            {
                "doc_id": "xxx",
                "doc_name": "xxx",
                "similarity_score": 0.85,
                "metadata": {...}
            },
            ...
        ]

        说明：
            直接使用原始查询进行向量检索，返回top-k结果。
            理由：
            1. 语义向量检索本身就能理解自然语言
            2. 原始查询包含完整的用户意图
            3. 第2次改写（文档特定改写）更重要，第1次改写作用有限
            4. 减少LLM调用，提高效率
        """
        logger.info(f"")
        logger.info(f"=" * 80)
        logger.info(f"🔍 [Selector] ========== 智能文档选择 ==========")
        logger.info(f"=" * 80)
        logger.info(f"📝 [Selector] 原始查询: {query[:100]}...")
        logger.info(f"📊 [Selector] 配置:")
        logger.info(f"   - 最多选择: {max_docs} 个文档")

        if not self.metadata_db:
            logger.error(f"❌ [Selector] 元数据向量数据库未初始化，无法选择文档")
            return []

        try:
            # 直接使用原始查询进行向量检索
            logger.info(f"")
            logger.info(f"🔍 [Selector] 向量检索（top-{max_docs}）")
            logger.info(f"📝 [Selector] 使用原始查询（语义向量检索无需改写）")

            selected_docs = self.metadata_db.search_similar_docs(
                query=query,  # 直接使用原始查询
                top_k=max_docs
            )

            logger.info(f"📊 [Selector] 向量检索返回: {len(selected_docs)} 个文档")

            logger.info(f"")
            logger.info(f"=" * 80)
            logger.info(f"✅ [Selector] 文档选择完成")
            logger.info(f"=" * 80)
            logger.info(f"📊 [Selector] 从 {self.registry.count()} 个注册文档中选择了 {len(selected_docs)} 个")

            if selected_docs:
                logger.info(f"📚 [Selector] 选中的文档:")
                for idx, doc in enumerate(selected_docs, 1):
                    logger.info(f"   {idx}. {doc['doc_name']} (相似度: {doc['similarity_score']:.3f})")
            else:
                logger.warning(f"⚠️  [Selector] 未找到相似度满足要求的文档")

            logger.info(f"=" * 80)
            logger.info(f"")

            return selected_docs

        except Exception as e:
            logger.error(f"❌ [Selector] 文档选择失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []

    # ==================== 已废弃的方法 ====================
    # 第1次改写（QUERY_REWRITER）已废弃：
    # 原因：语义向量检索本身就能理解自然语言，第2次文档特定改写更有效
    # 保留代码仅供参考

    # async def _rewrite_query(self, query: str) -> str:
    #     """
    #     [已废弃] 改写query，提取核心关键信息
    #
    #     废弃原因：
    #     1. 语义向量检索本身就能理解自然语言
    #     2. 第2次改写（文档特定改写）更重要且更精准
    #     3. 减少LLM调用，提高效率
    #     """
    #     from src.agents.answer.prompts import AnswerRole
    #
    #     prompt = f"""原始查询：{query}
    #
    # 请提取这个查询的核心关键信息，用于文档检索。要求：
    # 1. 提取主要关键词（名词、专业术语）
    # 2. 保留重要的动词（如"对比"、"分析"、"总结"）
    # 3. 去除冗余的口语化表达（"请帮我"、"麻烦"等）
    # 4. 如果涉及特定领域，保留领域术语
    #
    # 只返回改写后的查询，不要解释。"""
    #
    #     try:
    #         rewritten = await self.llm.async_call_llm_chain(
    #             role=AnswerRole.QUERY_REWRITER,
    #             input_prompt=prompt,
    #             session_id="query_rewrite_for_selection"
    #         )
    #
    #         return rewritten.strip()
    #
    #     except Exception as e:
    #         logger.error(f"❌ [Selector] Query改写失败: {e}，使用原始查询")
    #         return query
