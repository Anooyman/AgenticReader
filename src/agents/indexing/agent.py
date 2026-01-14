"""
Indexing Agent - 文档索引构建Agent

负责文档的解析、摘要生成、标签分类、向量索引构建和文档注册
"""

from langgraph.graph import StateGraph, END
from typing import Dict, List
import logging
import json
import re

from ..base import AgentBase
from .state import IndexingState
from .doc_registry import DocumentRegistry

logger = logging.getLogger(__name__)


class IndexingAgent(AgentBase):
    """
    索引构建Agent

    工作流程：
    1. parse - 解析文档内容
    2. chunk - 文本分块
    3. summarize - 生成摘要
    4. tag - 自动标签分类
    5. build_index - 构建向量索引
    6. register - 注册到文档库

    工具方法（直接在类中实现）：
    - extract_basic_info_impl - 提取基本信息
    - generate_summary_impl - 生成摘要
    - auto_tag_impl - 自动标签
    - build_vector_index_impl - 构建向量索引
    """

    def __init__(self):
        super().__init__(name="IndexingAgent")

        self.doc_registry = DocumentRegistry()
        self.graph = self.build_graph()

    def build_graph(self) -> StateGraph:
        """构建LangGraph workflow"""
        workflow = StateGraph(IndexingState)

        # 添加节点
        workflow.add_node("parse", self.parse_document)
        workflow.add_node("chunk", self.chunk_text)
        workflow.add_node("summarize", self.generate_summary)
        workflow.add_node("tag", self.auto_tag)
        workflow.add_node("build_index", self.build_index)
        workflow.add_node("register", self.register_document)

        # 添加边
        workflow.add_edge("parse", "chunk")
        workflow.add_edge("chunk", "summarize")
        workflow.add_edge("summarize", "tag")
        workflow.add_edge("tag", "build_index")
        workflow.add_edge("build_index", "register")
        workflow.add_edge("register", END)

        # 设置入口和出口
        workflow.set_entry_point("parse")

        return workflow.compile()

    # ==================== 工具方法实现 ====================

    async def generate_summary_impl(self, content: str, doc_name: str) -> str:
        """
        生成文档简要摘要（工具方法）

        Args:
            content: 文档内容
            doc_name: 文档名称

        Returns:
            简要摘要文本
        """
        logger.info(f"📝 [Tool:generate_summary] 生成摘要: {doc_name}")

        try:
            from src.config.prompts.reader_prompts import ReaderRole

            query = (
                "请按照文章本身的章节信息和叙事结构，整理这篇文章的主要内容，"
                "每个章节都需要有一定的简单介绍。如果背景知识中有一些文章的基本信息也需要一并总结。"
                "仅需要返回相关内容，多余的话无需返回。返回中文。"
            )

            context = {"全文内容": content}

            # 使用Agent的LLM实例
            answer = self.llm.get_answer(
                retrieval_data_dict=context,
                query=query,
                answer_role=ReaderRole.CONTEXT_QA
            )

            if not answer or not answer.strip():
                logger.error("生成的简要摘要为空")
                return f"文档 {doc_name} 的简要摘要（生成失败）"

            logger.info(f"✅ [Tool:generate_summary] 摘要生成完成，长度: {len(answer)} 字符")
            return answer

        except Exception as e:
            logger.error(f"❌ [Tool:generate_summary] 生成摘要失败: {e}")
            return f"文档 {doc_name} 的简要摘要（生成错误: {str(e)}）"

    async def auto_tag_impl(self, doc_name: str, brief_summary: str, max_tags: int = 5) -> List[str]:
        """
        自动为文档生成分类标签（工具方法）

        Args:
            doc_name: 文档名称
            brief_summary: 文档简要摘要
            max_tags: 最大标签数量

        Returns:
            标签列表
        """
        logger.info(f"🏷️ [Tool:auto_tag] 自动生成标签: {doc_name}")

        if not brief_summary:
            logger.warning("摘要为空，返回默认标签")
            return ["未分类"]

        try:
            prompt = f"""
请为以下文档生成3-{max_tags}个分类标签。

文档名称：{doc_name}
文档摘要：{brief_summary}

要求：
1. 标签应该反映文档的主题、领域、类型
2. 使用简短的词或短语（2-5个字）
3. 返回JSON格式：{{"tags": ["标签1", "标签2", ...]}}

只返回JSON，不要其他内容。
"""

            # 使用Agent的LLM实例
            response = await self.llm.async_get_response(prompt)

            # 解析LLM返回的JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    tags = result.get("tags", [])

                    if len(tags) > max_tags:
                        tags = tags[:max_tags]

                    logger.info(f"✅ [Tool:auto_tag] 生成标签: {tags}")
                    return tags

                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️ [Tool:auto_tag] JSON解析失败: {e}")

            # 失败时尝试从文档名提取标签
            logger.warning("LLM返回格式不正确，尝试从文档名提取标签")
            fallback_tags = self._extract_tags_from_filename(doc_name)
            return fallback_tags if fallback_tags else ["未分类"]

        except Exception as e:
            logger.error(f"❌ [Tool:auto_tag] 生成标签失败: {e}")
            return ["未分类"]

    async def build_vector_index_impl(
        self,
        doc_name: str,
        chunks: List[str],
        metadata: Dict = None
    ) -> str:
        """
        构建向量索引（工具方法）

        Args:
            doc_name: 文档名称
            chunks: 文本分块列表
            metadata: 元数据

        Returns:
            索引路径
        """
        logger.info(f"🔨 [Tool:build_index] 构建向量索引: {doc_name}, 分块数: {len(chunks)}")

        try:
            from pathlib import Path
            from src.config.settings import DATA_ROOT

            # 使用Agent的embedding模型
            embedding_model = self.embedding_model

            # 构建索引路径
            index_dir = Path(DATA_ROOT) / "vector_db" / doc_name
            index_dir.mkdir(parents=True, exist_ok=True)

            # TODO: 实际的向量索引构建逻辑
            # 使用 VectorDBClient 构建索引

            index_path = str(index_dir)

            logger.info(f"✅ [Tool:build_index] 索引构建完成: {index_path}")
            return index_path

        except Exception as e:
            logger.error(f"❌ [Tool:build_index] 索引构建失败: {e}")
            raise

    def _extract_tags_from_filename(self, filename: str) -> List[str]:
        """
        从文件名中提取可能的标签

        Args:
            filename: 文件名

        Returns:
            标签列表
        """
        name_without_ext = filename.rsplit('.', 1)[0]

        keywords_map = {
            'ml': '机器学习',
            'ai': '人工智能',
            'deep': '深度学习',
            'paper': '论文',
            'report': '报告',
            'tutorial': '教程',
            'guide': '指南',
            'doc': '文档',
            'manual': '手册',
        }

        tags = []
        name_lower = name_without_ext.lower()

        for keyword, tag in keywords_map.items():
            if keyword in name_lower:
                tags.append(tag)

        return tags

    # ==================== Workflow节点方法 ====================

    async def parse_document(self, state: IndexingState) -> Dict:
        """
        步骤1：解析文档内容

        根据doc_type选择合适的Parser
        """
        logger.info(f"📄 [Parse] 解析文档: {state['doc_name']}")

        try:
            doc_type = state["doc_type"]
            doc_path = state["doc_path"]

            if doc_type == "pdf":
                # TODO: 使用PDFReader提取内容
                # 临时实现：读取文件
                from pathlib import Path
                if Path(doc_path).exists():
                    raw_data = f"PDF content from {doc_path}"
                else:
                    raw_data = "Sample PDF content for testing"

            elif doc_type == "url":
                # TODO: 使用WebReader提取内容
                raw_data = f"Web content from {doc_path}"

            else:
                raise ValueError(f"不支持的文档类型: {doc_type}")

            logger.info(f"✅ [Parse] 解析完成，内容长度: {len(raw_data)}")

            return {
                "raw_data": raw_data,
                "status": "parsed"
            }

        except Exception as e:
            logger.error(f"❌ [Parse] 解析失败: {e}")
            return {
                "status": "error",
                "error": str(e)
            }

    async def chunk_text(self, state: IndexingState) -> Dict:
        """
        步骤2：文本分块
        """
        logger.info(f"✂️ [Chunk] 文本分块: {state['doc_name']}")

        try:
            from src.processing.text.splitter import StrictOverlapSplitter

            # 创建分块器
            splitter = StrictOverlapSplitter(
                token_threshold=1000,
                overlap=1
            )

            # 执行分块
            raw_data = state.get("raw_data", "")
            chunks = splitter.split_text(raw_data)

            logger.info(f"✅ [Chunk] 分块完成，共 {len(chunks)} 个分块")

            return {
                "chunks": chunks,
                "status": "chunked"
            }

        except Exception as e:
            logger.error(f"❌ [Chunk] 分块失败: {e}")
            return {
                "status": "error",
                "error": str(e)
            }

    async def generate_summary(self, state: IndexingState) -> Dict:
        """
        步骤3：生成摘要
        """
        logger.info(f"📝 [Summarize] 生成摘要: {state['doc_name']}")

        try:
            raw_data = state.get("raw_data", "")
            doc_name = state["doc_name"]

            # 调用工具方法（直接调用，不通过execute_tool）
            brief_summary = await self.generate_summary_impl(raw_data, doc_name)

            logger.info(f"✅ [Summarize] 摘要生成完成")

            return {
                "brief_summary": brief_summary,
                "status": "summarized"
            }

        except Exception as e:
            logger.error(f"❌ [Summarize] 摘要生成失败: {e}")
            return {
                "status": "error",
                "error": str(e)
            }

    async def auto_tag(self, state: IndexingState) -> Dict:
        """
        步骤4：自动标签分类
        """
        logger.info(f"🏷️ [Tag] 自动标签: {state['doc_name']}")

        try:
            doc_name = state["doc_name"]
            brief_summary = state.get("brief_summary", "")

            # 调用工具方法（直接调用）
            auto_tags = await self.auto_tag_impl(doc_name, brief_summary)

            # 合并手动标签
            manual_tags = state.get("manual_tags", []) or []
            final_tags = list(set(auto_tags + manual_tags))

            logger.info(f"✅ [Tag] 标签生成完成: {final_tags}")

            return {
                "auto_tags": auto_tags,
                "tags": final_tags,
                "status": "tagged"
            }

        except Exception as e:
            logger.error(f"❌ [Tag] 标签生成失败: {e}")
            # 失败时使用manual_tags
            return {
                "auto_tags": [],
                "tags": state.get("manual_tags", []) or [],
                "status": "tagged"
            }

    async def build_index(self, state: IndexingState) -> Dict:
        """
        步骤5：构建向量索引
        """
        logger.info(f"🔨 [BuildIndex] 构建索引: {state['doc_name']}")

        try:
            doc_name = state["doc_name"]
            chunks = state.get("chunks", [])
            tags = state.get("tags", [])
            brief_summary = state.get("brief_summary", "")

            # 调用工具方法（直接调用）
            index_path = await self.build_vector_index_impl(
                doc_name,
                chunks,
                metadata={
                    "tags": tags,
                    "summary": brief_summary
                }
            )

            logger.info(f"✅ [BuildIndex] 索引构建完成: {index_path}")

            return {
                "index_path": index_path,
                "status": "indexed"
            }

        except Exception as e:
            logger.error(f"❌ [BuildIndex] 索引构建失败: {e}")
            return {
                "status": "error",
                "error": str(e)
            }

    async def register_document(self, state: IndexingState) -> Dict:
        """
        步骤6：注册到文档库
        """
        logger.info(f"📋 [Register] 注册文档: {state['doc_name']}")

        try:
            # 注册文档
            doc_id = self.doc_registry.register(
                doc_name=state["doc_name"],
                doc_path=state["doc_path"],
                doc_type=state["doc_type"],
                index_path=state.get("index_path", ""),
                tags=state.get("tags", []),
                brief_summary=state.get("brief_summary", ""),
                metadata={
                    "auto_tags": state.get("auto_tags", []),
                    "manual_tags": state.get("manual_tags", [])
                }
            )

            logger.info(f"✅ [Register] 文档注册完成: {doc_id}")

            return {
                "doc_id": doc_id,
                "status": "completed"
            }

        except Exception as e:
            logger.error(f"❌ [Register] 文档注册失败: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
