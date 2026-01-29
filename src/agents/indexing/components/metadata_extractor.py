"""
元数据提取器

从文档中提取增强元数据，用于文档语义检索和相关性匹配
"""

import logging
import json
import re
from typing import Dict, Any

logger = logging.getLogger(__name__)


class MetadataExtractor:
    """元数据提取器 - 从文档中提取丰富的元数据"""

    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLM客户端实例
        """
        self.llm = llm_client

    async def extract_metadata(
        self,
        doc_name: str,
        brief_summary: str,
        structure: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        使用LLM从文档信息中提取增强元数据

        Args:
            doc_name: 文档名称
            brief_summary: 简要摘要（已有）
            structure: 章节结构信息

        Returns:
            元数据字典：
            {
                "title": str,
                "keywords": List[str],
                "abstract": str,
                "topics": List[str],
                "extended_summary": str,
                "embedding_summary": str
            }
        """
        logger.info(f"📋 [MetadataExtractor] 开始提取文档元数据: {doc_name}")

        try:
            # 构建输入prompt
            structure_str = json.dumps(structure, ensure_ascii=False, indent=2)

            input_prompt = f"""文档名称：{doc_name}

简要摘要：
{brief_summary}

章节结构：
{structure_str}

请提取元数据。"""

            # 调用LLM提取元数据
            from src.config.prompts.metadata_prompts import MetadataRole

            response = await self.llm.async_call_llm_chain(
                role=MetadataRole.METADATA_EXTRACTOR,
                input_prompt=input_prompt,
                session_id="metadata_extraction"
            )

            logger.info(f"📤 [MetadataExtractor] LLM响应预览: {response[:100]}...")

            # 解析JSON响应
            metadata = self._parse_metadata_response(response)

            # 验证元数据
            if self._validate_metadata(metadata):
                logger.info(f"✅ [MetadataExtractor] 元数据提取完成")
                logger.info(f"   - 标题: {metadata.get('title', 'N/A')}")
                logger.info(f"   - 关键词数量: {len(metadata.get('keywords', []))}")
                logger.info(f"   - 主题数量: {len(metadata.get('topics', []))}")
                logger.info(f"   - 摘要长度: {len(metadata.get('abstract', ''))} 字符")
                return metadata
            else:
                logger.warning("⚠️ [MetadataExtractor] 元数据验证失败，使用降级方案")
                return self._create_fallback_metadata(doc_name, brief_summary, structure)

        except Exception as e:
            logger.error(f"❌ [MetadataExtractor] 提取元数据失败: {e}")
            logger.info(f"📝 [MetadataExtractor] 使用降级方案生成元数据")
            return self._create_fallback_metadata(doc_name, brief_summary, structure)

    def _parse_metadata_response(self, response: str) -> Dict[str, Any]:
        """
        解析LLM返回的JSON元数据

        Args:
            response: LLM响应文本

        Returns:
            解析后的元数据字典
        """
        try:
            # 尝试提取JSON部分
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                metadata = json.loads(json_match.group())
                return metadata
            else:
                logger.warning("⚠️ [MetadataExtractor] 未找到JSON格式，尝试直接解析")
                return json.loads(response)

        except json.JSONDecodeError as e:
            logger.error(f"❌ [MetadataExtractor] JSON解析失败: {e}")
            return {}

    def _validate_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        验证元数据完整性

        Args:
            metadata: 元数据字典

        Returns:
            是否有效
        """
        required_fields = [
            "title",
            "keywords",
            "abstract",
            "topics",
            "extended_summary",
            "embedding_summary"
        ]

        for field in required_fields:
            if field not in metadata:
                logger.warning(f"⚠️ [MetadataExtractor] 缺少字段: {field}")
                return False

            # 检查字段类型和内容
            if field in ["keywords", "topics"]:
                if not isinstance(metadata[field], list) or len(metadata[field]) == 0:
                    logger.warning(f"⚠️ [MetadataExtractor] 字段 {field} 格式无效或为空")
                    return False
            else:
                if not isinstance(metadata[field], str) or not metadata[field].strip():
                    logger.warning(f"⚠️ [MetadataExtractor] 字段 {field} 格式无效或为空")
                    return False

        return True

    def _create_fallback_metadata(
        self,
        doc_name: str,
        brief_summary: str,
        structure: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        创建降级元数据（当LLM提取失败时）

        Args:
            doc_name: 文档名称
            brief_summary: 简要摘要
            structure: 章节结构 (agenda_dict: {chapter_title: [page_numbers]})

        Returns:
            降级元数据
        """
        logger.info(f"📝 [MetadataExtractor] 生成降级元数据")

        try:
            # 从文档名提取标题（去除扩展名）
            title = doc_name.replace('.pdf', '').replace('.txt', '').replace('_', ' ')

            # 从章节结构提取关键词（章节标题）
            keywords = []
            if structure and isinstance(structure, dict):
                # structure 是 agenda_dict: {chapter_title: [page_numbers]}
                keywords = [str(k) for k in structure.keys()][:10]

            # 如果没有关键词，使用文档名作为关键词
            if not keywords:
                # 从文档名中提取关键词（按空格或下划线分割）
                keywords = [word for word in title.replace('_', ' ').split() if len(word) > 2][:10]

            # 使用brief_summary作为abstract
            abstract = brief_summary if brief_summary else f"文档：{title}"

            # 主题从章节标题中提取
            topics = keywords[:5] if keywords else [title]

            # extended_summary 组合brief_summary和章节列表
            extended_summary = f"{brief_summary}\n\n"
            if keywords:
                extended_summary += "主要章节：\n"
                for idx, chapter in enumerate(keywords[:10], 1):
                    extended_summary += f"{idx}. {chapter}\n"
            else:
                extended_summary += "（未检测到明确的章节结构）\n"

            # embedding_summary
            keyword_str = ', '.join(keywords) if keywords else title
            embedding_summary = f"标题：{title}\n关键词：{keyword_str}\n摘要：{abstract}"

            metadata = {
                "title": title,
                "keywords": keywords if keywords else [title],
                "abstract": abstract,
                "topics": topics,
                "extended_summary": extended_summary,
                "embedding_summary": embedding_summary
            }

            logger.info(f"✅ [MetadataExtractor] 降级元数据生成完成")
            logger.info(f"   - 标题: {title}")
            logger.info(f"   - 关键词数量: {len(metadata['keywords'])}")
            logger.info(f"   - 主题数量: {len(metadata['topics'])}")

            return metadata

        except Exception as e:
            logger.error(f"❌ [MetadataExtractor] 降级元数据生成失败: {e}")
            # 最小化降级方案
            title = doc_name.replace('.pdf', '').replace('.txt', '')
            return {
                "title": title,
                "keywords": [title],
                "abstract": f"文档：{title}",
                "topics": [title],
                "extended_summary": f"文档：{title}",
                "embedding_summary": f"标题：{title}"
            }
