"""
Retrieval Agent - 智能检索Agent

使用ReAct（Reasoning + Acting）模式进行智能检索
"""

from langgraph.graph import StateGraph, END
from langgraph.types import Command
from typing import Dict, List, Any
import logging
import json
import re

from ..base import AgentBase
from .state import RetrievalState
from src.config.prompts.reader_prompts import ReaderRole
from src.utils.helpers import extract_data_from_LLM_res

logger = logging.getLogger(__name__)


class RetrievalAgent(AgentBase):
    """
    检索Agent（ReAct模式）

    工作流程（循环）：
    1. think - 思考下一步使用哪个工具
    2. act - 执行工具调用
    3. observe - 观察结果
    4. evaluate - 评估是否完成

    工具方法（直接在类中实现）：
    - search_by_context - 语义相似检索
    - search_by_title - 按标题检索
    - get_document_structure - 获取文档结构

    支持：
    - 单文档检索：指定doc_name
    - 多文档检索：doc_name=None
    - 标签过滤：指定tags
    """

    def __init__(self, doc_name: str = None):
        super().__init__(name="RetrievalAgent")

        # 当前文档上下文
        self.current_doc = doc_name
        self.current_tags = None

        # 初始化 VectorDBClient（复用实例，避免重复加载）
        self.vector_db_client = None
        if doc_name:
            self.vector_db_client = self._create_vector_db_client(doc_name)

        # 检索缓存字典（提升性能，避免重复检索）
        self.retrieval_data_dict: Dict[str, Any] = {}

        self.graph = self.build_graph()

    def _get_db_path_from_doc_name(self, doc_name: str) -> str:
        """
        将文档名称转换为向量数据库路径

        Args:
            doc_name: 文档名称

        Returns:
            str: 向量数据库的完整路径
        """
        from pathlib import Path
        from src.config.settings import DATA_ROOT

        db_path = Path(DATA_ROOT) / "vector_db" / doc_name
        return str(db_path)

    def _create_vector_db_client(self, doc_name: str):
        """
        创建 VectorDBClient 实例

        Args:
            doc_name: 文档名称

        Returns:
            VectorDBClient: 向量数据库客户端实例
        """
        from src.core.vector_db.vector_db_client import VectorDBClient

        db_path = self._get_db_path_from_doc_name(doc_name)

        # 使用依赖注入，传入 embedding_model
        client = VectorDBClient(
            db_path=db_path,
            embedding_model=self.embedding_model
        )

        logger.info(f"✅ [VectorDB] 已创建向量数据库客户端: {doc_name}")
        return client

    def _build_retrieval_tools(self) -> Dict[str, Dict]:
        """
        从配置文件构建检索工具字典

        工具配置来源：src/config/tools/retrieval_tools.py

        Returns:
            工具字典，key为工具名称，value包含工具详细信息
        """
        from src.config.tools.retrieval_tools import get_enabled_tools

        tools = {}
        enabled_tools = get_enabled_tools()

        for tool_config in enabled_tools:
            tool_name = tool_config["name"]
            method_name = tool_config["method_name"]

            # 获取对应的方法
            if hasattr(self, method_name):
                tool_method = getattr(self, method_name)

                tools[tool_name] = {
                    "name": tool_name,
                    "description": tool_config["description"],
                    "parameters": tool_config["parameters"],
                    "function": tool_method,
                    "priority": tool_config.get("priority", 999),
                }

                logger.debug(f"已加载工具: {tool_name} (方法: {method_name})")
            else:
                logger.warning(f"工具 '{tool_name}' 配置的方法 '{method_name}' 未找到")

        logger.info(f"成功加载 {len(tools)} 个检索工具")
        return tools

    def _get_agenda_dict_from_vector_db(self) -> Dict[str, Any]:
        """
        从向量数据库获取 agenda_dict（内部方法）

        从 type="structure" 文档中提取 agenda_dict 元数据。

        Returns:
            agenda_dict 字典，如果获取失败返回空字典
        """
        if not self.vector_db_client:
            logger.warning("⚠️ [_get_agenda_dict_from_vector_db] VectorDBClient 未初始化")
            return {}

        try:
            doc_res = self.vector_db_client.search_with_metadata_filter(
                query="",
                k=1,
                field_name="type",
                field_value="structure",
                enable_dedup=False
            )

            if doc_res and len(doc_res) > 0:
                document = doc_res[0][0] if isinstance(doc_res[0], tuple) else doc_res[0]
                agenda_dict = document.metadata.get("agenda_dict", {})
                logger.debug(f"✅ [_get_agenda_dict_from_vector_db] 获取到 agenda_dict，共 {len(agenda_dict)} 个章节")
                return agenda_dict
            else:
                logger.warning("⚠️ [_get_agenda_dict_from_vector_db] 未找到文档结构信息")
                return {}

        except Exception as e:
            logger.error(f"❌ [_get_agenda_dict_from_vector_db] 获取 agenda_dict 失败: {e}")
            return {}

    # ==================== 工具方法实现 ====================

    async def search_by_context(self, query: str) -> List[str]:
        """
        基于上下文的语义检索方法

        通过向量相似度搜索在文档中查找与查询语义相关的内容段落。
        这个方法使用向量数据库的语义搜索功能，能够理解查询的语义含义，
        并找到在语义上相关的文档内容，即使关键词不完全匹配。

        Args:
            query: 搜索查询字符串，应描述要查找的内容语义

        Returns:
            检索到的相关文档内容列表
        """
        if not query or not query.strip():
            logger.warning("❌ [Tool:search_by_context] 查询字符串为空")
            return []

        if not self.vector_db_client:
            logger.error("❌ [Tool:search_by_context] 向量数据库未初始化")
            return []

        try:
            # 使用 type='context' 过滤器进行语义搜索，启用去重
            doc_res = self.vector_db_client.search_with_metadata_filter(
                query=query,
                k=3,  # 与旧实现保持一致
                field_name="type",
                field_value="context",
                enable_dedup=True
            )

            context_data = []
            chapter_info_list = []  # 存储章节信息用于汇总

            if doc_res and len(doc_res) > 0:
                for idx, doc_item in enumerate(doc_res):
                    try:
                        # 解析文档结构
                        document = doc_item[0] if isinstance(doc_item, tuple) else doc_item
                        metadata = document.metadata

                        refactor_data = metadata.get("refactor", "")
                        raw_data = metadata.get("raw_data", {})
                        page_number = list(raw_data.keys()) if isinstance(raw_data, dict) else []

                        # 提取章节标题信息
                        chapter_title = metadata.get("title", "未知章节")

                        # 整理并返回检索到的数据（包含元数据）
                        if refactor_data and refactor_data.strip():
                            # 检查是否已存在相同内容（去重）
                            existing_contents = [item["content"] for item in context_data]
                            if refactor_data not in existing_contents:
                                # 返回结构化数据：包含内容和元数据
                                context_data.append({
                                    "content": refactor_data,
                                    "title": chapter_title,
                                    "pages": sorted(page_number, key=lambda x: int(x) if str(x).isdigit() else 0) if page_number else []
                                })

                                # 记录章节信息用于日志汇总
                                chapter_info_list.append({
                                    "title": chapter_title,
                                    "pages": sorted(page_number, key=lambda x: int(x) if str(x).isdigit() else 0) if page_number else []
                                })

                    except Exception as e:
                        logger.error(f"❌ [Tool:search_by_context] 处理第 {idx+1} 个文档时出错: {e}")
                        continue

                # ========== 汇总日志 ==========
                logger.info("")
                logger.info("=" * 60)
                logger.info("✅ [CONTEXT RETRIEVAL] 上下文检索结果")
                logger.info("=" * 60)
                logger.info(f"📊 返回 {len(context_data)} 条内容片段")

                # 显示本次返回内容对应的章节和页码
                if chapter_info_list:
                    logger.info("📚 检索到的章节:")
                    for idx, chapter in enumerate(chapter_info_list, 1):
                        pages_str = f"页码: {', '.join(map(str, chapter['pages']))}" if chapter['pages'] else "无页码"
                        logger.info(f"   {idx}. {chapter['title']} ({pages_str})")
                else:
                    logger.info("📚 未检索到任何章节")

                logger.info("=" * 60)
                logger.info("")
            else:
                logger.warning("⚠️ [Tool:search_by_context] 在向量数据库中未找到与查询相关的内容")

            return context_data

        except Exception as e:
            logger.error(f"❌ [Tool:search_by_context] 通过上下文检索数据时出错: {e}", exc_info=True)
            return []

    async def extract_titles_from_structure(self, query: str) -> List[str]:
        """
        从文档结构中提取相关标题列表

        根据用户查询，从 type="structure" 文档中获取 agenda_dict，
        然后使用 LLM 智能提取与查询相关的章节标题。

        Args:
            query: 用户查询字符串

        Returns:
            提取到的标题列表
        """
        logger.info(f"📋 [Tool:extract_titles_from_structure] 从结构中提取标题: {query[:50]}...")

        if not query or not query.strip():
            logger.warning("❌ [Tool:extract_titles_from_structure] 查询字符串为空")
            return []

        if not self.vector_db_client:
            logger.error("❌ [Tool:extract_titles_from_structure] VectorDBClient 未初始化")
            return []

        try:
            # 步骤1: 从向量数据库获取 agenda_dict
            agenda_dict = self._get_agenda_dict_from_vector_db()

            if not agenda_dict:
                logger.warning("⚠️ [Tool:extract_titles_from_structure] 未找到文档结构信息")
                return []

            # 步骤2: 使用 LLM 提取标题列表
            response = self.llm.call_llm_chain(
                ReaderRole.CHAPTER_MATCHER,
                query,
                "chapter_matcher",
                system_format_dict={
                    "agenda_dict": agenda_dict
                }
            )

            response_data = extract_data_from_LLM_res(response)
            title_list = response_data.get("title", [])

            # 验证结果
            if not isinstance(title_list, list):
                logger.warning("⚠️ [Tool:extract_titles_from_structure] 标题列表格式无效")
                return []

            logger.info(f"✅ [Tool:extract_titles_from_structure] 提取到 {len(title_list)} 个标题: {title_list}")
            return title_list

        except Exception as e:
            logger.error(f"❌ [Tool:extract_titles_from_structure] 提取标题失败: {e}", exc_info=True)
            return []

    async def search_by_title(self, title_list: str) -> List[str]:
        """
        基于标题列表的精确检索工具

        根据给定的标题列表，在向量数据库中精确匹配这些标题来检索对应的文档内容。

        Args:
            title_list: 标题列表（JSON格式字符串或列表）

        Returns:
            检索到的匹配标题的文档内容列表
        """
        logger.info(f"📑 [Tool:search_by_title] 标题检索: {title_list}")

        if not self.vector_db_client:
            logger.error("❌ [Tool:search_by_title] VectorDBClient 未初始化")
            return []

        try:
            # 解析 title_list（可能是字符串或列表）
            if isinstance(title_list, str):
                # 尝试解析为JSON
                try:
                    parsed_list = json.loads(title_list)
                    if isinstance(parsed_list, list):
                        title_list = parsed_list
                    else:
                        logger.warning("⚠️ [Tool:search_by_title] 解析后的数据不是列表")
                        return []
                except json.JSONDecodeError:
                    # 如果不是JSON，按逗号分割
                    title_list = [t.strip() for t in title_list.split(',') if t.strip()]

            # 输入验证
            if not isinstance(title_list, list):
                logger.warning("⚠️ [Tool:search_by_title] 标题列表格式无效，期望list类型")
                return []

            if len(title_list) == 0:
                logger.info("ℹ️ [Tool:search_by_title] 标题列表为空，返回空结果")
                return []

            logger.info(f"📝 [Tool:search_by_title] 处理 {len(title_list)} 个标题: {title_list}")

        except Exception as e:
            logger.error(f"❌ [Tool:search_by_title] 解析标题列表失败: {e}")
            return []

        # 遍历标题列表，检索对应内容
        context_data = []
        successful_retrievals = 0
        cache_hits = 0
        returned_titles = []  # 追踪实际返回的标题

        for title in title_list:
            if not title or not isinstance(title, str):
                continue

            title = title.strip()
            if not title:
                continue

            try:
                refactor_data = ""
                page_number = []
                is_from_cache = False

                # 检查缓存
                if title in self.retrieval_data_dict:
                    cached_data = self.retrieval_data_dict[title]
                    refactor_data = cached_data.get("data", "")
                    page_number = cached_data.get("page", [])
                    cache_hits += 1
                    is_from_cache = True
                else:
                    # 从向量数据库检索（仅检索 type='title' 的文档）
                    try:
                        doc_res = self.vector_db_client.search_by_title(
                            title,
                            doc_type="title",
                            enable_dedup=True
                        )

                        if doc_res and len(doc_res) > 0:
                            # 处理返回的列表中的每个文档
                            all_refactor_data = []
                            all_page_numbers = []

                            for doc_item in doc_res:
                                document = doc_item[0] if isinstance(doc_item, tuple) else doc_item
                                metadata = document.metadata

                                item_refactor_data = metadata.get("refactor", "")
                                item_raw_data = metadata.get("raw_data", {})
                                item_page_numbers = list(item_raw_data.keys()) if isinstance(item_raw_data, dict) else []

                                if item_refactor_data and item_refactor_data.strip():
                                    all_refactor_data.append(item_refactor_data)

                                if item_page_numbers:
                                    all_page_numbers.extend(item_page_numbers)

                            # 合并所有检索到的数据
                            refactor_data = "\n\n".join(all_refactor_data) if all_refactor_data else ""
                            page_number = list(set(all_page_numbers))  # 去重页面编号

                            # 缓存检索结果
                            self.retrieval_data_dict[title] = {
                                "data": refactor_data,
                                "page": page_number
                            }

                            successful_retrievals += 1
                        else:
                            logger.warning(f"⚠️ [Tool:search_by_title] 章节 '{title}' 在向量数据库中未找到")

                    except Exception as e:
                        logger.error(f"❌ [Tool:search_by_title] 检索章节 '{title}' 时出错: {e}")
                        continue

                # 添加到上下文数据（去重），包含元数据
                if refactor_data and refactor_data.strip():
                    # 检查是否已存在相同内容
                    existing_contents = [item["content"] if isinstance(item, dict) else item for item in context_data]
                    if refactor_data not in existing_contents:
                        # 返回结构化数据：包含内容和元数据
                        context_data.append({
                            "content": refactor_data,
                            "title": title,
                            "pages": sorted(page_number, key=lambda x: int(x) if str(x).isdigit() else 0) if page_number else []
                        })
                        # 记录用于日志汇总
                        returned_titles.append({
                            "title": title,
                            "pages": page_number,
                            "from_cache": is_from_cache
                        })

            except Exception as e:
                logger.error(f"❌ [Tool:search_by_title] 处理章节 '{title}' 时发生错误: {e}")
                continue

        # ========== 汇总日志 ==========
        logger.info("")
        logger.info("=" * 60)
        logger.info("✅ [TITLE RETRIEVAL] 标题检索结果")
        logger.info("=" * 60)
        logger.info(f"📊 返回 {len(context_data)} 条内容片段 (新检索: {successful_retrievals}, 缓存: {cache_hits})")

        # 显示本次实际返回的章节和页码
        if returned_titles:
            logger.info("📚 本次返回的章节:")
            for item in returned_titles:
                title = item["title"]
                pages = item["pages"]
                from_cache = item.get("from_cache", False)

                cache_tag = " [缓存]" if from_cache else " [新检索]"

                if pages:
                    sorted_pages = sorted(pages, key=lambda x: int(x) if str(x).isdigit() else 0)
                    pages_str = f"页码: {', '.join(map(str, sorted_pages))}"
                else:
                    pages_str = "无页码"
                logger.info(f"   ✓ {title} ({pages_str}){cache_tag}")
        else:
            logger.info("📚 未检索到任何内容")

        logger.info("=" * 60)
        logger.info("")

        return context_data

    async def get_document_structure(self, query: str = "") -> List[str]:
        """
        获取文档的目录结构工具

        从向量数据库中检索 type="structure" 的特殊文档，获取文档结构信息。

        Args:
            query: 查询参数（此工具不需要具体查询内容，保留用于接口兼容）

        Returns:
            文档目录结构列表
        """
        _ = query  # 参数保留用于接口兼容，实际不使用
        logger.info(f"📚 [Tool:get_document_structure] 从向量数据库获取文档结构")

        if not self.vector_db_client:
            logger.error("❌ [Tool:get_document_structure] VectorDBClient 未初始化")
            return ["文档结构信息不可用（向量数据库未初始化）"]

        try:
            # 获取 agenda_dict
            agenda_dict = self._get_agenda_dict_from_vector_db()

            if not agenda_dict:
                logger.warning("⚠️ [Tool:get_document_structure] 文档结构信息为空")
                return ["文档目录信息不可用"]

            # 格式化目录结构
            structure_list = []
            structure_list.append("=" * 60)
            structure_list.append("📑 文档目录结构")
            structure_list.append("=" * 60)

            for title, page_info in agenda_dict.items():
                if isinstance(page_info, list):
                    if len(page_info) == 0:
                        page_str = "页码未知"
                    elif len(page_info) == 1:
                        page_str = f"页码: {page_info[0]}"
                    else:
                        sorted_pages = sorted(page_info, key=lambda x: int(x) if str(x).isdigit() else 0)
                        page_str = f"页码: {sorted_pages[0]}-{sorted_pages[-1]}"
                else:
                    page_str = f"页码: {page_info}"

                structure_list.append(f"{title} ({page_str})")

            structure_list.append("=" * 60)

            logger.info(f"✅ [Tool:get_document_structure] 获取到 {len(agenda_dict)} 个章节")
            return structure_list

        except Exception as e:
            logger.error(f"❌ [Tool:get_document_structure] 获取失败: {e}", exc_info=True)
            return ["文档结构信息不可用"]

    # ==================== Workflow节点方法 ====================

    def build_graph(self) -> StateGraph:
        """构建ReAct workflow"""
        workflow = StateGraph(RetrievalState)

        # 添加节点
        workflow.add_node("initialize", self.initialize)
        workflow.add_node("think", self.think)
        workflow.add_node("act", self.act)
        workflow.add_node("observe", self.observe)
        workflow.add_node("evaluate", self.evaluate)
        workflow.add_node("summary", self.summary)

        # 添加边
        workflow.add_edge("initialize", "think")
        workflow.add_edge("think", "act")
        workflow.add_edge("act", "observe")
        workflow.add_edge("observe", "evaluate")

        # 条件边：根据评估结果决定继续或结束
        workflow.add_conditional_edges(
            "evaluate",
            self.should_continue,
            {
                "continue": "think",  # 继续循环
                "finish": "summary"  # 先到 summary 节点总结
            }
        )

        # summary 节点完成后到 END
        workflow.add_edge("summary", END)

        # 设置入口
        workflow.set_entry_point("initialize")

        return workflow.compile()

    def _validate_state(self, state: RetrievalState) -> None:
        """
        验证state的完整性

        Args:
            state: RetrievalState对象

        Raises:
            ValueError: 缺少必需字段时抛出异常
        """
        required_fields = ['query', 'max_iterations']

        for field in required_fields:
            if field not in state:
                raise ValueError(f"❌ [Validate] State缺少必需字段: {field}")

        # 验证字段类型和值
        if not isinstance(state.get('query', ''), str) or not state.get('query', '').strip():
            raise ValueError("❌ [Validate] query字段必须是非空字符串")

        max_iterations = state.get('max_iterations', 0)
        if not isinstance(max_iterations, int) or max_iterations <= 0:
            raise ValueError("❌ [Validate] max_iterations必须是正整数")

        logger.debug(f"✅ [Validate] State验证通过")

    async def initialize(self, state: RetrievalState) -> Dict:
        """
        初始化节点：设置Agent的上下文环境

        在workflow开始时执行一次，包括：
        1. 验证state完整性
        2. 设置文档上下文
        3. 创建或更新 VectorDBClient
        4. 初始化必要的state字段
        """
        try:
            # 验证state
            self._validate_state(state)

            # 从state中读取并设置文档上下文
            doc_name_from_state = state.get('doc_name')
            self.current_doc = doc_name_from_state or self.current_doc
            self.current_tags = state.get('tags')

            logger.info(f"🔧 [Initialize] 文档上下文: {self.current_doc}, 标签: {self.current_tags}")
            logger.info(f"🔧 [Initialize] 查询: {state['query'][:50]}...")
            logger.info(f"🔧 [Initialize] 最大迭代次数: {state['max_iterations']}")

            # 创建或更新 VectorDBClient（如果文档名称变化）
            if self.current_doc:
                if self.vector_db_client is None:
                    # 首次创建
                    self.vector_db_client = self._create_vector_db_client(self.current_doc)
                    logger.info(f"✅ [Initialize] VectorDBClient 已创建并加载")

                elif doc_name_from_state and doc_name_from_state != self.current_doc:
                    # 文档名称变化，重新创建
                    logger.info(f"🔄 [Initialize] 文档名称变化，重新创建VectorDBClient")
                    self.vector_db_client = self._create_vector_db_client(doc_name_from_state)
                    self.current_doc = doc_name_from_state
            else:
                logger.warning(f"⚠️ [Initialize] 未指定文档名称，某些检索功能可能无法使用")

            # 初始化必要的state字段
            if 'retrieved_content' not in state:
                state['retrieved_content'] = {}

            if 'thoughts' not in state:
                state['thoughts'] = []

            if 'actions' not in state:
                state['actions'] = []

            if 'observations' not in state:
                state['observations'] = []

            if 'current_iteration' not in state:
                state['current_iteration'] = 0

            logger.info(f"✅ [Initialize] 初始化完成")
            return state

        except ValueError as e:
            logger.error(f"❌ [Initialize] 状态验证失败: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ [Initialize] 初始化失败: {e}", exc_info=True)
            raise

    async def think(self, state: RetrievalState) -> Dict:
        """
        步骤1：思考下一步使用哪个工具

        基于当前查询和已检索内容，决定下一步动作
        """
        current_iteration = state.get("current_iteration", 0)

        logger.info(
            f"🤔 [Think] 迭代 {current_iteration + 1}/{state['max_iterations']}"
        )

        try:
            # 获取工具描述（从配置文件）
            from src.config.tools.retrieval_tools import format_all_tools_for_llm
            tools_description = format_all_tools_for_llm()

            # 构建prompt（简化版本）
            prompt = f"""
你是一个智能检索助手。当前任务是为用户查询检索相关内容。

用户查询：{state['query']}
当前已检索到 {len(state.get('retrieved_content', {{}}))} 个内容片段。

已执行的动作：
{state.get('actions', [])}

可用工具：
{tools_description}

请选择下一步使用哪个工具，并提供查询字符串。

返回JSON格式：
{{
    "thought": "你的思考过程",
    "action": "工具名称",
    "action_input": "查询字符串"
}}

只返回JSON，不要其他内容。
"""

            # 使用 async_call_llm_chain
            session_id = f"retrieval_{state.get('doc_name', 'default')}"
            response = await self.llm.async_call_llm_chain(
                role=ReaderRole.RETRIEVAL,
                input_prompt=prompt,
                session_id=session_id,
                system_format_dict={"tool_info_dict": tools_description}
            )

            # 解析JSON - 更健壮的解析方法
            decision = None
            try:
                # 方法1: 尝试直接解析整个响应
                decision = json.loads(response.strip())
            except json.JSONDecodeError:
                try:
                    # 方法2: 使用正则提取JSON对象（非贪婪匹配，处理嵌套）
                    json_match = re.search(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}', response, re.DOTALL)
                    if json_match:
                        decision = json.loads(json_match.group())
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.warning(f"⚠️ [Think] JSON解析失败: {e}, 使用默认策略")

            # 提取决策字段
            if decision and isinstance(decision, dict):
                thought = decision.get("thought", "")
                action = decision.get("action", "search_by_context")
                action_input = decision.get("action_input", state["query"])
            else:
                # 默认使用语义检索
                thought = "默认策略：JSON解析失败"
                action = "search_by_context"
                action_input = state["query"]

            logger.info(f"💡 [Think] 选择工具: {action}")
            logger.debug(f"思考过程: {thought}")

            # 更新状态
            state["thoughts"] = state.get("thoughts", []) + [thought]
            state["current_tool"] = action
            state["current_params"] = {"query": action_input}
            state["current_iteration"] = current_iteration + 1

            return state

        except Exception as e:
            logger.error(f"❌ [Think] 思考失败: {e}")

            # 失败时使用默认策略
            state["current_tool"] = "search_by_context"
            state["current_params"] = {"query": state["query"]}
            state["thoughts"] = state.get("thoughts", []) + ["思考失败，使用默认策略"]
            state["current_iteration"] = current_iteration + 1

            return state

    async def act(self, state: RetrievalState) -> Dict:
        """
        步骤2：执行工具调用

        支持多种参数传递方式：
        - 单参数工具：params = {"query": "..."}
        - 多参数工具：params = {"query": "...", "k": 5, "doc_type": "title"}
        """
        tool_name = state["current_tool"]
        params = state.get("current_params", {})

        logger.info(f"🔧 [Act] 执行工具: {tool_name}")
        logger.debug(f"参数: {params}")

        try:
            # 构建可用工具字典
            available_tools = self._build_retrieval_tools()

            # 执行工具
            if tool_name in available_tools:
                tool_func = available_tools[tool_name]["function"]

                # 智能参数传递：检查函数签名
                import inspect
                sig = inspect.signature(tool_func)
                func_params = list(sig.parameters.keys())

                # 如果函数只接受一个参数（除了self），直接传query
                if len(func_params) == 1 and 'query' in params:
                    result = await tool_func(params['query'])
                # 否则尝试解包所有参数
                else:
                    # 过滤出函数实际需要的参数
                    filtered_params = {k: v for k, v in params.items() if k in func_params}
                    result = await tool_func(**filtered_params)

            else:
                logger.warning(f"⚠️ [Act] 未知工具: {tool_name}，使用默认检索")
                query = params.get("query", state.get("query", ""))
                result = await self.search_by_context(query)

            logger.info(f"✅ [Act] 工具执行完成，返回 {len(result) if isinstance(result, list) else 'dict'} 个结果")

            # 记录动作
            state["actions"] = state.get("actions", []) + [{
                "tool": tool_name,
                "params": params
            }]
            state["last_result"] = result

            return state

        except Exception as e:
            logger.error(f"❌ [Act] 工具执行失败: {e}", exc_info=True)

            # 返回空结果，但保留动作记录
            state["actions"] = state.get("actions", []) + [{
                "tool": tool_name,
                "params": params,
                "error": str(e)
            }]
            state["last_result"] = []

            return state

    async def observe(self, state: RetrievalState) -> Dict:
        """
        步骤3：观察结果，更新检索内容
        """
        logger.info(f"👀 [Observe] 观察结果")

        try:
            last_result = state.get("last_result", [])
            retrieved_content = state.get("retrieved_content", {})
            tool_name = state.get("current_tool", "")

            # 处理工具返回的结果
            if isinstance(last_result, list):
                doc_name = state.get('doc_name', 'doc')

                # 根据工具类型区分处理
                if tool_name == "get_document_structure":
                    # 文档结构信息作为特殊条目（List[str]）
                    retrieved_content["_structure"] = "\n".join(last_result)
                    logger.info(f"✅ [Observe] 已保存文档结构信息")
                else:
                    # 检索结果内容，处理新的结构化格式 List[Dict] 或旧的 List[str]
                    for idx, item in enumerate(last_result):
                        if isinstance(item, dict):
                            # 新格式：包含 content、title、pages 的字典
                            content = item.get("content", "")
                            title = item.get("title", "未知章节")
                            pages = item.get("pages", [])

                            if content and content.strip():
                                # 使用工具名和索引构建唯一key
                                key = f"{doc_name}_{tool_name}_{idx}"
                                retrieved_content[key] = {
                                    "content": content,
                                    "title": title,
                                    "pages": pages
                                }
                        elif isinstance(item, str):
                            # 兼容旧格式：纯字符串
                            if item and item.strip():
                                key = f"{doc_name}_{tool_name}_{idx}"
                                retrieved_content[key] = {
                                    "content": item,
                                    "title": "未知章节",
                                    "pages": []
                                }

                    logger.info(f"✅ [Observe] 新增 {len(last_result)} 个检索结果")

            elif isinstance(last_result, dict):
                # 兼容Dict格式（未来可能的扩展）
                if "results" in last_result:
                    for item in last_result.get("results", []):
                        source = item.get("metadata", {}).get("page", "unknown")
                        content = item.get("content", "")
                        if content:
                            key = f"{state.get('doc_name', 'doc')}_{source}"
                            retrieved_content[key] = content
                elif "chapters" in last_result:
                    chapters_info = last_result.get("chapters", [])
                    retrieved_content["_structure"] = chapters_info

            # 记录观察（简化的结果摘要）
            result_summary = f"Tool: {tool_name}, Results: {len(last_result) if isinstance(last_result, list) else 'dict'}"
            state["observations"] = state.get("observations", []) + [result_summary]
            state["retrieved_content"] = retrieved_content

            logger.info(f"✅ [Observe] 已检索内容总数: {len([k for k in retrieved_content.keys() if not k.startswith('_')])}")

            return state

        except Exception as e:
            logger.error(f"❌ [Observe] 观察失败: {e}", exc_info=True)

            # 失败时保持原有状态
            return state

    async def evaluate(self, state: RetrievalState) -> Dict:
        """
        步骤4：评估是否已获取足够信息
        """
        logger.info(f"⚖️ [Evaluate] 评估检索结果")

        try:
            # 使用Agent级别的LLM实例
            llm = self.llm

            # 整理已检索内容
            retrieved_content = state.get("retrieved_content", {})
            content_items = []
            for key, value in retrieved_content.items():
                if key.startswith("_"):
                    continue

                if isinstance(value, dict):
                    # 新格式：包含 content、title、pages
                    content = value.get("content", "")
                    title = value.get("title", "未知章节")
                    preview = content[:100] + "..." if len(content) > 100 else content
                    content_items.append(f"- {title}: {preview}")
                else:
                    # 旧格式：字符串
                    preview = value[:100] + "..." if len(value) > 100 else value
                    content_items.append(f"- {key}: {preview}")

            content_summary = "\n".join(content_items)

            prompt = f"""
评估检索结果是否足以回答用户查询。

用户查询：{state['query']}
已检索内容摘要：
{content_summary}

已检索条数：{len([k for k in retrieved_content.keys() if not k.startswith('_')])}

判断是否已获取足够信息来回答查询。

返回JSON格式：
{{
    "is_complete": true/false,
    "reason": "评估原因",
    "confidence": 0.0-1.0
}}

只返回JSON，不要其他内容。
"""

            # 使用 async_call_llm_chain
            session_id = f"retrieval_{state.get('doc_name', 'default')}"
            response = await llm.async_call_llm_chain(
                role=ReaderRole.RETRIEVAL_EVALUATOR,
                input_prompt=prompt,
                session_id=session_id
            )

            # 解析JSON - 更健壮的解析方法
            evaluation = None
            try:
                # 方法1: 尝试直接解析整个响应
                evaluation = json.loads(response.strip())
            except json.JSONDecodeError:
                try:
                    # 方法2: 使用正则提取JSON对象
                    json_match = re.search(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}', response, re.DOTALL)
                    if json_match:
                        evaluation = json.loads(json_match.group())
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.warning(f"⚠️ [Evaluate] JSON解析失败: {e}, 使用默认评估")

            # 提取评估结果
            if evaluation and isinstance(evaluation, dict):
                is_complete = evaluation.get("is_complete", False)
                reason = evaluation.get("reason", "")
            else:
                # 默认：如果有内容就认为完成
                is_complete = len(retrieved_content) > 0
                reason = "默认评估：JSON解析失败"

            logger.info(f"✅ [Evaluate] 评估结果: {'完成' if is_complete else '继续'} - {reason}")

            state["is_complete"] = is_complete
            return state

        except Exception as e:
            logger.error(f"❌ [Evaluate] 评估失败: {e}")

            # 失败时根据迭代次数判断
            current_iteration = state.get("current_iteration", 0)
            is_complete = current_iteration >= state["max_iterations"]

            state["is_complete"] = is_complete
            return state

    async def summary(self, state: RetrievalState) -> Dict:
        """
        步骤5：总结检索结果

        使用 LLM 将检索到的内容格式化，包括：
        - 内容来源（title、pages）
        - 内容摘要
        """
        logger.info(f"📝 [Summary] 开始总结检索结果")

        try:
            retrieved_content = state.get("retrieved_content", {})

            # 过滤出实际检索的内容（排除特殊条目）
            content_items = []
            for key, value in retrieved_content.items():
                if key.startswith("_"):
                    continue  # 跳过特殊条目（如 _structure）

                if isinstance(value, dict):
                    # 新格式：包含 content、title、pages
                    content_items.append({
                        "content": value.get("content", ""),
                        "title": value.get("title", "未知章节"),
                        "pages": value.get("pages", [])
                    })
                elif isinstance(value, str):
                    # 旧格式兼容：纯字符串
                    content_items.append({
                        "content": value,
                        "title": "未知章节",
                        "pages": []
                    })

            if not content_items:
                logger.warning("⚠️ [Summary] 没有检索到任何内容")
                state["final_summary"] = "未检索到相关内容。"
                return state

            # 构建 LLM 提示
            items_text = ""
            for idx, item in enumerate(content_items, 1):
                pages_str = ", ".join(map(str, item["pages"])) if item["pages"] else "未知"
                items_text += f"\n\n【条目 {idx}】\n"
                items_text += f"来源章节: {item['title']}\n"
                items_text += f"页码: {pages_str}\n"
                items_text += f"内容:\n{item['content'][:500]}{'...' if len(item['content']) > 500 else ''}\n"

            prompt = f"""
请对以下检索结果进行格式化总结。

用户查询：{state.get('query', '')}

检索到 {len(content_items)} 条内容：
{items_text}

请按照以下格式总结：

## 📚 检索结果总结

### 📑 来源信息
- 涉及章节：[列出所有相关章节标题]
- 涉及页码：[列出所有页码范围]

### 📝 内容摘要
[对检索到的内容进行归纳总结，突出与用户查询相关的关键信息]

### 📄 详细内容
[按章节组织，展示每个章节的具体内容]

请用清晰、专业的语言进行总结。
"""

            # 使用 async_call_llm_chain
            session_id = f"retrieval_{state.get('doc_name', 'default')}"
            summary_result = await self.llm.async_call_llm_chain(
                role=ReaderRole.CONTEXT_SUMMARIZER,
                input_prompt=prompt,
                session_id=session_id
            )

            logger.info(f"✅ [Summary] 总结完成，长度: {len(summary_result)} 字符")

            state["final_summary"] = summary_result
            return state

        except Exception as e:
            logger.error(f"❌ [Summary] 总结失败: {e}", exc_info=True)

            # 失败时返回简单的提示信息
            retrieved_content = state.get("retrieved_content", {})
            content_count = len([k for k in retrieved_content.keys() if not k.startswith("_")])

            fallback_summary = f"总结生成失败，但已检索到 {content_count} 条相关内容。"

            state["final_summary"] = fallback_summary
            return state

    def should_continue(self, state: RetrievalState) -> str:
        """
        判断是否继续检索

        Returns:
            "continue" 或 "finish"
        """
        # 检查是否完成
        if state.get("is_complete", False):
            return "finish"

        # 检查是否超过最大迭代次数
        current_iteration = state.get("current_iteration", 0)
        max_iterations = state.get("max_iterations", 5)

        if current_iteration >= max_iterations:
            logger.warning(f"⚠️ 达到最大迭代次数: {max_iterations}")
            return "finish"

        return "continue"

