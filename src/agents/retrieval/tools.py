"""
RetrievalAgent 工具方法实现

所有检索相关的工具方法
"""

from typing import List, Dict, TYPE_CHECKING
import logging
import json

if TYPE_CHECKING:
    from .agent import RetrievalAgent

logger = logging.getLogger(__name__)


class RetrievalTools:
    """RetrievalAgent 工具方法集合"""

    def __init__(self, agent: 'RetrievalAgent'):
        """
        Args:
            agent: RetrievalAgent实例（依赖注入）
        """
        self.agent = agent

    async def search_by_context(self, query: str) -> Dict:
        """
        基于上下文的语义检索方法

        通过向量相似度搜索在文档中查找与查询语义相关的内容段落。

        Args:
            query: 搜索查询字符串，应描述要查找的内容语义

        Returns:
            标准格式的工具响应：
            {
                "type": "content",
                "tool": "search_by_context",
                "items": [{"content": ..., "title": ..., "pages": ..., "raw_data": ...}, ...]
            }
        """
        from ..common.tool_response_format import create_content_response
        logger.info(f"🔍 [Tool:search_by_context] ---------- 语义检索 ----------")
        logger.info(f"🔍 [Tool:search_by_context] 查询内容: {query}")

        if not query or not query.strip():
            logger.warning("🔍 [Tool:search_by_context] ❌ 查询字符串为空")
            return []

        if not self.agent.vector_db_client:
            logger.error("🔍 [Tool:search_by_context] ❌ 向量数据库未初始化")
            return []

        try:
            logger.info(f"🔍 [Tool:search_by_context] 执行向量检索 (k=3, type=context)")
            # 使用 type='context' 过滤器进行语义搜索，启用去重
            doc_res = self.agent.vector_db_client.search_with_metadata_filter(
                query=query,
                k=3,
                field_name="type",
                field_value="context",
                enable_dedup=True,
                conversation_turn=getattr(self.agent, "current_conversation_turn", 0)
            )
            logger.info(f"🔍 [Tool:search_by_context] 向量检索返回: {len(doc_res) if doc_res else 0} 个结果")

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
                                # 返回结构化数据：包含内容、元数据和原始数据
                                context_data.append({
                                    "content": refactor_data,  # refactor 后的内容，用于 evaluate
                                    "title": chapter_title,
                                    "pages": sorted(page_number, key=lambda x: int(x) if str(x).isdigit() else 0) if page_number else [],
                                    "raw_data": raw_data  # 原始数据，用于 format 生成最终答案
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

            # 返回标准格式
            return create_content_response("search_by_context", context_data)

        except ValueError as e:
            # Embedding维度不匹配等配置错误
            error_msg = str(e)
            if "Embedding维度不匹配" in error_msg or "维度" in error_msg:
                logger.error(f"❌ [Tool:search_by_context] {error_msg}")
                # 向用户返回友好的错误提示
                error_info = [{
                    "content": (
                        "⚠️ 检索失败：Embedding模型配置不匹配\n\n"
                        "问题：当前使用的embedding模型与索引时使用的模型不同，导致向量维度不匹配。\n\n"
                        "解决方案：\n"
                        "1. 检查并恢复索引时使用的embedding模型配置\n"
                        "2. 或者删除旧的向量数据库并重新索引文档\n\n"
                        f"详细错误信息：\n{error_msg}"
                    ),
                    "title": "系统错误",
                    "pages": [],
                    "raw_data": {}
                }]
                return create_content_response("search_by_context", error_info)
            else:
                logger.error(f"❌ [Tool:search_by_context] 配置错误: {e}", exc_info=True)
                return create_content_response("search_by_context", [])

        except Exception as e:
            logger.error(f"❌ [Tool:search_by_context] 通过上下文检索数据时出错: {e}", exc_info=True)
            # 错误时返回空结果的标准格式
            return create_content_response("search_by_context", [])

    async def extract_titles_from_structure(self, query: str) -> Dict:
        """
        从文档结构中提取相关标题列表（带选择原因）

        根据用户查询，从 type="structure" 文档中获取 agenda_dict，
        然后使用 LLM 智能提取与查询相关的章节标题，并说明选择原因。

        Args:
            query: 用户查询字符串

        Returns:
            标准格式的工具响应：
            {
                "type": "metadata",
                "tool": "extract_titles_from_structure",
                "items": ["章节1", "章节2", ...],
                "metadata": {"reason": "选择这些章节的原因"}
            }
        """
        from src.utils.helpers import extract_data_from_LLM_res
        from src.agents.common.prompts import CommonRole
        from ..common.tool_response_format import create_metadata_response

        logger.info(f"📋 [Tool:extract_titles_from_structure] 从结构中提取标题: {query[:50]}...")

        if not query or not query.strip():
            logger.warning("❌ [Tool:extract_titles_from_structure] 查询字符串为空")
            return create_metadata_response("extract_titles_from_structure", [], {"reason": "查询为空"})

        if not self.agent.vector_db_client:
            logger.error("❌ [Tool:extract_titles_from_structure] VectorDBClient 未初始化")
            return create_metadata_response("extract_titles_from_structure", [], {"reason": "向量数据库未初始化"})

        try:
            # 步骤1: 从向量数据库获取 agenda_dict
            agenda_dict = self.agent.utils.get_agenda_dict_from_vector_db()

            if not agenda_dict:
                logger.warning("⚠️ [Tool:extract_titles_from_structure] 未找到文档结构信息")
                return create_metadata_response("extract_titles_from_structure", [], {"reason": "未找到文档结构信息"})

            # 步骤2: 使用 LLM 提取标题列表和原因
            response = self.agent.llm.call_llm_chain(
                CommonRole.CHAPTER_MATCHER,
                query,
                "chapter_matcher",
                system_format_dict={
                    "agenda_dict": agenda_dict
                }
            )

            response_data = extract_data_from_LLM_res(response)
            title_list = response_data.get("title", [])
            reason = response_data.get("reason", "未提供选择原因")

            # 验证结果
            if not isinstance(title_list, list):
                logger.warning("⚠️ [Tool:extract_titles_from_structure] 标题列表格式无效")
                return create_metadata_response("extract_titles_from_structure", [], {"reason": "标题列表格式无效"})

            logger.info(f"✅ [Tool:extract_titles_from_structure] 提取到 {len(title_list)} 个标题")
            logger.info(f"📋 [Tool:extract_titles_from_structure]   - 标题: {title_list}")
            logger.info(f"📋 [Tool:extract_titles_from_structure]   - 原因: {reason}")

            # 返回标准格式
            return create_metadata_response(
                "extract_titles_from_structure",
                title_list,
                {"reason": reason}
            )

        except Exception as e:
            logger.error(f"❌ [Tool:extract_titles_from_structure] 提取标题失败: {e}", exc_info=True)
            return create_metadata_response("extract_titles_from_structure", [], {"reason": f"提取失败: {str(e)}"})

    async def search_by_title(self, title_list: str) -> Dict:
        """
        基于标题列表的精确检索工具

        根据给定的标题列表，在向量数据库中精确匹配这些标题来检索对应的文档内容。

        Args:
            title_list: 标题列表（JSON格式字符串或列表）

        Returns:
            标准格式的工具响应：
            {
                "type": "content",
                "tool": "search_by_title",
                "items": [{"content": ..., "title": ..., "pages": ..., "raw_data": ...}, ...]
            }
        """
        from ..common.tool_response_format import create_content_response
        logger.info(f"📑 [Tool:search_by_title] ---------- 标题检索 ----------")
        logger.info(f"📑 [Tool:search_by_title] 输入标题: {title_list}")

        if not self.agent.vector_db_client:
            logger.error("📑 [Tool:search_by_title] ❌ VectorDBClient 未初始化")
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
                raw_data = {}
                is_from_cache = False

                # 检查缓存
                if title in self.agent.retrieval_data_dict:
                    cached_data = self.agent.retrieval_data_dict[title]
                    refactor_data = cached_data.get("data", "")
                    page_number = cached_data.get("page", [])
                    raw_data = cached_data.get("raw_data", {})
                    cache_hits += 1
                    is_from_cache = True
                else:
                    # 从向量数据库检索（仅检索 type='title' 的文档）
                    try:
                        doc_res = self.agent.vector_db_client.search_by_title(
                            title,
                            doc_type="title",
                            enable_dedup=True,
                            conversation_turn=getattr(self.agent, "current_conversation_turn", 0)
                        )

                        if doc_res and len(doc_res) > 0:
                            # 处理返回的列表中的每个文档
                            all_refactor_data = []
                            all_page_numbers = []
                            merged_raw_data = {}  # 合并所有文档的 raw_data

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

                                # 合并 raw_data
                                if isinstance(item_raw_data, dict):
                                    merged_raw_data.update(item_raw_data)

                            # 合并所有检索到的数据
                            refactor_data = "\n\n".join(all_refactor_data) if all_refactor_data else ""
                            page_number = list(set(all_page_numbers))  # 去重页面编号

                            # 缓存检索结果（包含 raw_data）
                            self.agent.retrieval_data_dict[title] = {
                                "data": refactor_data,
                                "page": page_number,
                                "raw_data": merged_raw_data
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
                        # 返回结构化数据：包含内容、元数据和原始数据
                        context_data.append({
                            "content": refactor_data,  # refactor 后的内容，用于 evaluate
                            "title": title,
                            "pages": sorted(page_number, key=lambda x: int(x) if str(x).isdigit() else 0) if page_number else [],
                            "raw_data": raw_data  # 原始数据，用于 format 生成最终答案
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

        # 返回标准格式
        return create_content_response("search_by_title", context_data)

    async def get_document_structure(self, query: str = "") -> Dict:
        """
        获取文档的目录结构工具

        从向量数据库中检索 type="structure" 的特殊文档，获取文档结构信息。

        Args:
            query: 查询参数（此工具不需要具体查询内容，保留用于接口兼容）

        Returns:
            标准格式的工具响应：
            {
                "type": "structure",
                "tool": "get_document_structure",
                "items": ["第1章 引言", "第2章 背景", ...]
            }
        """
        from ..common.tool_response_format import create_structure_response

        _ = query  # 参数保留用于接口兼容，实际不使用
        logger.info(f"📚 [Tool:get_document_structure] ---------- 获取文档结构 ----------")

        if not self.agent.vector_db_client:
            logger.error("📚 [Tool:get_document_structure] ❌ VectorDBClient 未初始化")
            return create_structure_response("get_document_structure", ["文档结构信息不可用（向量数据库未初始化）"])

        try:
            # 获取 agenda_dict
            agenda_dict = self.agent.utils.get_agenda_dict_from_vector_db()

            if not agenda_dict:
                logger.warning("⚠️ [Tool:get_document_structure] 文档结构信息为空")
                return create_structure_response("get_document_structure", ["文档目录信息不可用"])

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
            # 返回标准格式
            return create_structure_response("get_document_structure", structure_list)

        except Exception as e:
            logger.error(f"❌ [Tool:get_document_structure] 获取失败: {e}", exc_info=True)
            return create_structure_response("get_document_structure", ["文档结构信息不可用"])
