"""
跨文档综合器

综合多个文档的检索结果，生成统一的、带出处标注的答案
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class CrossDocumentSynthesizer:
    """跨文档综合器 - 综合多文档检索结果"""

    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLM客户端实例
        """
        self.llm = llm_client

    async def synthesize(
        self,
        query: str,
        multi_doc_results: Dict[str, Any]
    ) -> str:
        """
        综合多文档检索结果

        Args:
            query: 用户查询
            multi_doc_results: 并行检索的结果（来自ParallelRetrievalCoordinator）

        Returns:
            综合后的最终答案（带出处标注）
        """
        logger.info(f"")
        logger.info(f"=" * 80)
        logger.info(f"🔗 [Synthesizer] ========== 跨文档综合 ==========")
        logger.info(f"=" * 80)
        logger.info(f"📝 [Synthesizer] 查询: {query[:100]}...")
        logger.info(f"📊 [Synthesizer] 接收到 {len(multi_doc_results)} 个文档的检索结果")

        try:
            # Step 1: 格式化每个文档的结果
            logger.info(f"")
            logger.info(f"📋 [Synthesizer] 步骤1: 格式化多文档结果")
            formatted_results = self._format_multi_doc_results(multi_doc_results)

            if not formatted_results.strip():
                logger.warning(f"⚠️  [Synthesizer] 所有文档检索结果为空")
                return "抱歉，未能从相关文档中检索到足够的信息来回答您的问题。"

            # Step 2: 使用LLM综合生成答案
            logger.info(f"")
            logger.info(f"🤖 [Synthesizer] 步骤2: LLM综合生成答案")
            final_answer = await self._llm_synthesize(query, formatted_results)

            logger.info(f"")
            logger.info(f"=" * 80)
            logger.info(f"✅ [Synthesizer] 跨文档综合完成")
            logger.info(f"=" * 80)
            logger.info(f"📊 [Synthesizer] 答案长度: {len(final_answer)} 字符")
            logger.info(f"📊 [Synthesizer] 答案预览: {final_answer[:200]}...")
            logger.info(f"=" * 80)
            logger.info(f"")

            return final_answer

        except Exception as e:
            logger.error(f"❌ [Synthesizer] 综合失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return f"抱歉，综合多文档结果时出现错误：{str(e)}"

    def _format_multi_doc_results(self, results: Dict[str, Any]) -> str:
        """
        格式化多文档结果

        Output format:
        ========================================
        文档1: 论文A.pdf (相关性: 8.5)
        ========================================
        [检索内容]
        ...

        ========================================
        文档2: 论文B.pdf (相关性: 7.8)
        ========================================
        [检索内容]
        ...

        Args:
            results: 多文档检索结果

        Returns:
            格式化后的文本
        """
        formatted_sections = []
        success_count = 0
        error_count = 0

        for doc_name, result in results.items():
            # 跳过检索失败的文档
            if result.get("error"):
                logger.warning(f"⚠️  [Synthesizer] 文档 '{doc_name}' 检索失败，跳过: {result['error']}")
                error_count += 1
                continue

            source_metadata = result.get("source_metadata", {})
            relevance_score = source_metadata.get("similarity_score", "N/A")
            final_summary = result.get("final_summary", "")

            if not final_summary or not final_summary.strip():
                logger.warning(f"⚠️  [Synthesizer] 文档 '{doc_name}' 检索结果为空，跳过")
                continue

            # 格式化单个文档的结果
            section = f"""
========================================
文档: {doc_name} (相关性评分: {relevance_score if isinstance(relevance_score, str) else f'{relevance_score:.3f}'})
========================================
{final_summary}
"""
            formatted_sections.append(section)
            success_count += 1

        logger.info(f"📊 [Synthesizer] 格式化结果: 成功 {success_count} 个文档, 跳过 {error_count + (len(results) - success_count - error_count)} 个")

        return "\n\n".join(formatted_sections)

    async def _llm_synthesize(self, query: str, formatted_results: str) -> str:
        """
        使用LLM综合多文档内容

        Prompt策略:
        - 要求LLM综合多个文档的信息
        - 标注信息来源（文档名）
        - 处理冲突信息（如果不同文档说法不一致）
        - 保持客观性

        Args:
            query: 用户查询
            formatted_results: 格式化后的多文档结果

        Returns:
            综合答案
        """
        from src.agents.answer.prompts import AnswerRole

        prompt = f"""用户问题：{query}

以下是从多个相关文档中检索到的内容：

{formatted_results}

请根据以上多个文档的内容，综合回答用户问题。要求：
1. 综合所有相关信息，提供全面的答案
2. 明确标注信息来源（例如："根据文档A..."，"文档B指出..."）
3. 如果不同文档有冲突信息，请客观呈现并说明
4. 如果所有文档都无法回答问题，请明确说明
5. 保持答案的连贯性和可读性"""

        try:
            answer = await self.llm.async_call_llm_chain(
                role=AnswerRole.CROSS_DOC_SYNTHESIS,
                input_prompt=prompt,
                session_id="cross_doc_synthesis"
            )

            return answer

        except Exception as e:
            logger.error(f"❌ [Synthesizer] LLM调用失败: {e}")
            raise
