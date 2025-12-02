"""
Retrieval Agent Module

This module provides the RetrivalAgent class for intelligent document retrieval
from vector databases using both context-based and title-based search strategies.
"""
from typing import List, Dict, Any

from src.core.llm.client import LLMBase
from src.config.prompts.reader_prompts import ReaderRole
from src.config.tools.retrieval_tools import get_enabled_tools, format_tool_description, format_all_tools_for_llm
from src.core.vector_db.vector_db_client import VectorDBClient
from src.utils.helpers import *

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 使用LangChain原生的@tool装饰器，不需要自定义

class RetrivalAgent(LLMBase):
    """
    智能检索代理类
    
    该类继承自LLMBase，提供基于向量数据库的智能文档检索功能。
    支持两种检索策略：基于上下文的语义检索和基于标题的精确检索。
    
    Attributes:
        agenda_dict (Dict[str, Any]): 议程字典，包含文档结构信息
        vector_db_obj (VectorDBClient): 向量数据库客户端实例
        retrieval_data_dict (Dict[str, Any]): 检索结果缓存字典
    """

    def __init__(self, agenda_dict: Dict[str, Any], provider: str = "openai", vector_db_obj: VectorDBClient = None) -> None:
        """
        初始化检索代理
        
        Args:
            agenda_dict (Dict[str, Any]): 文档议程字典
            provider (str, optional): LLM提供商. Defaults to "openai".
            vector_db_obj (VectorDBClient, optional): 向量数据库客户端. Defaults to None.
        """
        logger.info(f"正在初始化检索代理，LLM提供商: {provider}")
        super().__init__(provider)
        self.agenda_dict = agenda_dict
        self.vector_db_obj = vector_db_obj
        self.retrieval_data_dict: Dict[str, Any] = {}
        
        # 验证初始化参数
        if not agenda_dict:
            logger.warning("议程字典为空，可能影响标题检索功能")
        if not vector_db_obj:
            logger.warning("向量数据库客户端未提供，检索功能将不可用")
        else:
            logger.info("检索代理初始化完成")

    def _build_retrieval_tools(self) -> Dict[str, Dict[str, Any]]:
        """
        从配置文件构建检索工具字典（ReAct 框架）

        工具配置来源：src/config/tools/retrieval_tools.py

        添加新工具的步骤：
        1. 在 src/config/tools/retrieval_tools.py 中添加工具配置
        2. 在本类中实现对应的方法（方法名与配置中的 method_name 一致）
        3. 工具会自动加载，无需修改此方法

        Returns:
            Dict[str, Dict[str, Any]]: 工具字典，key 为工具名称，value 包含工具的详细信息
        """
        # 从配置文件获取启用的工具
        enabled_tools_config = get_enabled_tools()

        # 构建工具字典
        tools = {}
        for tool_config in enabled_tools_config:
            tool_name = tool_config["name"]
            method_name = tool_config["method_name"]

            # 获取对应的方法
            if hasattr(self, method_name):
                tool_method = getattr(self, method_name)

                # 构建工具信息
                tools[tool_name] = {
                    "name": tool_name,
                    "description": tool_config["description"],
                    "parameters": tool_config["parameters"],
                    "function": tool_method,
                    "priority": tool_config.get("priority", 999),
                }

                logger.debug(f"已加载工具: {tool_name} (方法: {method_name})")
            else:
                logger.warning(f"工具 '{tool_name}' 配置的方法 '{method_name}' 在 RetrievalAgent 中未找到，已跳过")

        logger.info(f"成功加载 {len(tools)} 个检索工具")
        return tools

    def retrieval_data(self, query: str, max_iterations: int = 5, max_context_length: int = 10000, reset_history: bool = True) -> List[str]:
        """
        主检索方法 - 使用 ReAct 框架智能选择检索策略并评估结果

        该方法是 RetrivalAgent 的核心功能，使用 ReAct (Reasoning + Acting) 框架，
        通过 LLM 智能分析用户查询，决定使用哪个检索工具，执行检索，评估结果是否足够，
        并决定是否继续检索。

        完整 ReAct 工作流程：
        1. Thought: LLM 分析查询，决定使用哪个工具
        2. Action: 执行选定的工具
        3. Observation: 记录工具执行结果
        4. Evaluation: LLM 评估当前检索结果是否足够回答问题
        5. Decision: 根据评估决定是否继续检索（重复 1-4）

        可用工具：
        - retrieval_data_by_title: 基于标题的精确检索
        - retrieval_data_by_context: 基于语义的上下文检索
        - get_document_structure: 获取文档目录结构

        去重机制：
        - 使用文档内容哈希防止在 ReAct 循环中重复检索相同文档
        - 每次新查询开始时默认重置检索历史（可通过 reset_history=False 禁用）

        Args:
            query (str): 用户查询字符串
            max_iterations (int): 最大迭代次数，默认 5
            max_context_length (int): 触发上下文总结的最大长度，默认 10000
            reset_history (bool): 是否重置检索历史，默认 True

        Returns:
            List[str]: 检索到的文档内容列表（已去重和可能总结）

        Examples:
            >>> agent = RetrivalAgent(agenda_dict, vector_db_obj=db_client)
            >>> results = agent.retrieval_data("查找关于机器学习的章节")
            >>> print(f"检索到 {len(results)} 个相关内容")
        """
        logger.info(f"开始处理检索请求: {query[:100]}{'...' if len(query) > 100 else ''}")

        # 输入验证
        if not query or not query.strip():
            logger.warning("查询字符串为空")
            return []

        if not self.vector_db_obj:
            logger.error("向量数据库未初始化，无法进行检索")
            return []

        # 重置检索历史，防止跨查询的去重干扰
        if reset_history:
            self.vector_db_obj.reset_retrieval_history()

        # 构建可用的检索工具
        available_tools = self._build_retrieval_tools()
        tools_description = format_all_tools_for_llm()

        # ReAct 循环状态
        all_results = []
        iteration = 0

        try:
            while iteration < max_iterations:
                iteration += 1
                logger.info(f"ReAct 循环 - 第 {iteration}/{max_iterations} 轮")

                # Step 1: Thought - 让 LLM 决定使用哪个工具
                prompt = f"""用户查询: {query}

当前已检索到 {len(all_results)} 个内容片段。

请分析用户查询，选择最合适的工具来检索信息。

你必须返回以下 JSON 格式的响应:
{{
    "thought": "你的思考过程，分析为什么选择这个工具",
    "action": "选择的工具名称",
    "action_input": "传递给工具的查询参数"
}}

只返回 JSON，不要有其他文字。"""

                response = self.call_llm_chain(
                    ReaderRole.RETRIEVAL,
                    prompt,
                    "retrieval",
                    system_format_dict={"tool_info_dict": tools_description}
                )

                # Step 2: 解析 LLM 响应
                try:
                    action_decision = extract_data_from_LLM_res(response)
                    thought = action_decision.get("thought", "")
                    action = action_decision.get("action", "")
                    action_input = action_decision.get("action_input", query)

                    logger.info(f"LLM 选择: {action}")
                    logger.debug(f"思考过程: {thought}")

                except Exception as e:
                    logger.error(f"无法解析 LLM 响应: {e}")
                    logger.info("使用默认上下文检索")
                    action = "retrieval_data_by_context"
                    action_input = query

                # Step 3: Action - 执行选定的工具
                if action in available_tools:
                    tool_func = available_tools[action]["function"]
                    try:
                        logger.info(f"执行工具: {action}")
                        result = tool_func(action_input)

                        # Step 4: Observation - 记录结果
                        if isinstance(result, list):
                            all_results.extend(result)
                            logger.info(f"工具返回 {len(result)} 个结果")
                        elif result:
                            all_results.append(str(result))
                            logger.info(f"工具返回 1 个结果")

                    except Exception as e:
                        logger.error(f"工具执行失败: {e}")
                        continue
                else:
                    logger.warning(f"未知工具: {action}，使用默认检索")
                    result = self.retrieval_data_by_context(query)
                    all_results.extend(result)

                # Step 5: Evaluation - 评估当前检索结果是否足够
                if all_results:
                    # 先去重
                    unique_results = list(dict.fromkeys(all_results))

                    # 检查是否需要总结
                    total_length = sum(len(r) for r in unique_results)
                    if total_length > max_context_length:
                        logger.info(f"检索内容超过长度限制，进行总结")
                        summarized_for_eval = self._summarize_context(
                            unique_results,
                            query,
                            max_length=max_context_length
                        )
                        evaluation_context = summarized_for_eval
                    else:
                        evaluation_context = "\n\n".join(unique_results)

                    # 评估检索结果
                    evaluation = self._evaluate_retrieval_results(query, evaluation_context)

                    # Step 6: Decision - 根据评估决定是否继续
                    should_continue = evaluation.get("continue", False)
                    reason = evaluation.get("reason", "")

                    logger.info(f"评估结果: {'继续检索' if should_continue else '停止检索'}")
                    logger.info(f"理由: {reason}")

                    if not should_continue:
                        # 停止检索
                        logger.info(f"检索完成，共 {len(unique_results)} 个内容片段")
                        break

                    # 如果需要继续，查看建议的行动
                    suggested_action = evaluation.get("suggested_action")
                    if suggested_action:
                        logger.info(f"建议下一步使用工具: {suggested_action}")

            # 最终处理
            unique_results = list(dict.fromkeys(all_results))

            logger.info(f"ReAct 检索循环结束，共执行 {iteration} 轮")
            logger.info(f"最终结果: {len(unique_results)} 个内容片段")

            return unique_results

        except Exception as e:
            logger.error(f"检索过程中发生错误: {e}")
            import traceback
            logger.debug(f"{traceback.format_exc()}")
            return []

    def retrieval_data_by_context(self, query: str) -> List[str]:
        """
        基于上下文的语义检索方法

        通过向量相似度搜索在文档中查找与查询语义相关的内容段落。
        这个方法使用向量数据库的语义搜索功能，能够理解查询的语义含义，
        并找到在语义上相关的文档内容，即使关键词不完全匹配。

        Args:
            query (str): 搜索查询字符串，应描述要查找的内容语义

        Returns:
            List[str]: 检索到的相关文档内容列表
        """
        if not query or not query.strip():
            logger.warning("上下文检索: 查询字符串为空")
            return []

        if not self.vector_db_obj:
            logger.error("上下文检索: 向量数据库未初始化")
            return []

        try:
            # 使用 type='context' 过滤器进行语义搜索，启用去重
            doc_res = self.vector_db_obj.search_with_metadata_filter(
                query=query,
                k=3,
                field_name="type",
                field_value="context",
                enable_dedup=True  # 启用去重过滤
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

                        # 整理并返回检索到的数据
                        if refactor_data and refactor_data.strip():
                            if refactor_data not in context_data:
                                context_data.append(refactor_data)

                                # 记录章节信息用于最后汇总
                                chapter_info_list.append({
                                    "title": chapter_title,
                                    "pages": sorted(page_number, key=lambda x: int(x) if str(x).isdigit() else 0) if page_number else []
                                })

                    except Exception as e:
                        logger.error(f"处理第 {idx+1} 个文档时出错: {e}")
                        continue

                # ========== 汇总日志 ==========
                logger.info(f"")
                logger.info(f"{'='*60}")
                logger.info(f"✅ [CONTEXT RETRIEVAL] 上下文检索结果")
                logger.info(f"{'='*60}")
                logger.info(f"📊 返回 {len(context_data)} 条内容片段")
                
                # 🔥 显示本次返回内容对应的章节和页码
                if chapter_info_list:
                    logger.info(f"📚 检索到的章节:")
                    for idx, chapter in enumerate(chapter_info_list, 1):
                        pages_str = f"页码: {', '.join(map(str, chapter['pages']))}" if chapter['pages'] else "无页码"
                        logger.info(f"   {idx}. {chapter['title']} ({pages_str})")
                else:
                    logger.info(f"📚 未检索到任何章节")

                logger.info(f"{'='*60}")
                logger.info(f"")
            else:
                logger.warning(f"在向量数据库中未找到与查询相关的内容")

            return context_data

        except Exception as e:
            logger.error(f"通过上下文检索数据时出错: {e}")
            return []

    def retrieval_data_by_title(self, query: str) -> List[str]:
        """
        基于标题的精确检索方法

        这个方法首先使用LLM从用户查询中智能提取相关的章节标题关键词，
        然后在向量数据库中精确匹配这些标题来检索对应的文档内容。

        Args:
            query (str): 包含标题信息的查询字符串

        Returns:
            List[str]: 检索到的匹配标题的文档内容列表
        """
        if not query or not query.strip():
            logger.warning("标题检索: 查询字符串为空")
            return []

        try:
            response = self.call_llm_chain(
                ReaderRole.GETTITILE,
                query,
                "chat",
                system_format_dict={
                    "agenda_dict": self.agenda_dict
                }
            )

            response = extract_data_from_LLM_res(response)
            title_list = response.get("title", [])
            logger.info(f"提取到 {len(title_list) if isinstance(title_list, list) else 0} 个标题: {title_list}")

        except Exception as e:
            logger.error(f"LLM标题提取失败: {e}")
            return []

        # 输入验证
        if not isinstance(title_list, list):
            logger.warning("标题列表格式无效，期望list类型")
            return []

        if len(title_list) == 0:
            logger.info("未提取到任何标题，返回空结果")
            return []

        # 验证向量数据库是否可用
        if not self.vector_db_obj or not self.vector_db_obj.vector_db:
            logger.error("向量数据库未初始化")
            return []

        context_data = []
        successful_retrievals = 0
        cache_hits = 0
        returned_titles = []  # 🔥 追踪实际返回到 context_data 的标题

        for idx, title in enumerate(title_list):
            if not title or not isinstance(title, str):
                continue

            title = title.strip()
            if not title:
                continue

            try:
                refactor_data = ""
                page_number = []  # 初始化 page_number，避免未定义错误
                is_from_cache = False  # 🔥 追踪是否来自缓存

                # 检查缓存
                if title in self.retrieval_data_dict:
                    cached_data = self.retrieval_data_dict[title]
                    refactor_data = cached_data.get("data", "")
                    page_number = cached_data.get("page", [])
                    cache_hits += 1
                    is_from_cache = True  # 🔥 标记为缓存命中
                else:
                    # 从向量数据库检索（仅检索 type='title' 的文档），启用去重
                    try:
                        doc_res = self.vector_db_obj.search_by_title(title, doc_type="title", enable_dedup=True)

                        if doc_res and len(doc_res) > 0:
                            # 处理返回的列表中的每个文档
                            all_refactor_data = []
                            all_page_numbers = []

                            for doc_idx, doc_item in enumerate(doc_res):
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
                            logger.warning(f"章节 '{title}' 在向量数据库中未找到相关内容")

                    except Exception as e:
                        logger.error(f"检索章节 '{title}' 时出错: {e}")
                        continue

                # 添加到上下文数据（去重）
                if refactor_data and refactor_data.strip():
                    if refactor_data not in context_data:
                        context_data.append(refactor_data)
                        # 🔥 记录实际添加到 context_data 的标题、页码和是否缓存命中
                        returned_titles.append({
                            "title": title,
                            "pages": page_number,
                            "from_cache": is_from_cache
                        })

            except Exception as e:
                logger.error(f"处理章节 '{title}' 时发生错误: {e}")
                continue

        # ========== 汇总日志 ==========
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"✅ [TITLE RETRIEVAL] 标题检索结果")
        logger.info(f"{'='*60}")
        logger.info(f"📊 返回 {len(context_data)} 条内容片段 (新检索: {successful_retrievals}, 缓存: {cache_hits})")
        
        # 🔥 只显示本次实际返回到 context_data 的章节和页码
        if returned_titles:
            logger.info(f"📚 本次返回的章节:")
            for item in returned_titles:
                title = item["title"]
                pages = item["pages"]
                from_cache = item.get("from_cache", False)
                
                # 🔥 添加缓存标记
                cache_tag = " [缓存]" if from_cache else " [新检索]"
                
                if pages:
                    sorted_pages = sorted(pages, key=lambda x: int(x) if str(x).isdigit() else 0)
                    pages_str = f"页码: {', '.join(map(str, sorted_pages))}"
                else:
                    pages_str = "无页码"
                logger.info(f"   ✓ {title} ({pages_str}){cache_tag}")
        else:
            logger.info(f"📚 未检索到任何内容")
        
        logger.info(f"{'='*60}")
        logger.info(f"")

        return context_data

    def get_document_structure(self, query: str = "") -> List[str]:
        """
        获取文档的目录结构

        返回当前PDF文档的完整目录（章节）结构，包括所有章节标题和对应的页码信息。
        这个方法不进行实际的内容检索，只返回文档的组织结构。

        Args:
            query (str): 查询参数（此方法忽略该参数，总是返回完整目录）

        Returns:
            List[str]: 包含格式化的文档目录结构的列表，每个元素是一个章节的描述

        Examples:
            >>> agent = RetrivalAgent(agenda_dict, vector_db_obj=db_client)
            >>> structure = agent.get_document_structure()
            >>> print(structure[0])  # "第一章 引言 (页码: 1-10)"
        """
        if not self.agenda_dict:
            logger.warning("文档目录信息（agenda_dict）不可用")
            return ["文档目录信息不可用，无法获取文档结构。"]

        try:
            structure_list = []

            # 构建格式化的目录结构
            structure_header = "=" * 60 + "\n"
            structure_header += "📑 文档目录结构\n"
            structure_header += "=" * 60
            structure_list.append(structure_header)

            # 遍历 agenda_dict 并格式化每个章节
            for title, page_info in self.agenda_dict.items():
                # 格式化页码信息
                if isinstance(page_info, list):
                    if len(page_info) == 0:
                        page_str = "页码未知"
                    elif len(page_info) == 1:
                        page_str = f"页码: {page_info[0]}"
                    else:
                        # 排序页码
                        sorted_pages = sorted(page_info, key=lambda x: int(x) if str(x).isdigit() else 0)
                        page_str = f"页码: {sorted_pages[0]}-{sorted_pages[-1]}"
                elif isinstance(page_info, (int, str)):
                    page_str = f"页码: {page_info}"
                else:
                    page_str = "页码未知"

                # 格式化章节条目（不添加索引编号）
                chapter_entry = f"{title} ({page_str})"
                structure_list.append(chapter_entry)

            # 添加结尾分隔线
            structure_list.append("=" * 60)

            logger.info(f"文档目录结构获取完成，共解析 {len(self.agenda_dict)} 个章节")

            return structure_list

        except Exception as e:
            logger.error(f"获取文档目录结构时出错: {e}")
            return [f"获取文档目录结构失败: {str(e)}"]

    def _summarize_context(self, context_list: List[str], query: str, max_length: int = 10000) -> str:
        """
        总结检索到的上下文内容

        当检索到的内容过长时，使用 LLM 进行智能总结，保留关键信息。

        Args:
            context_list (List[str]): 检索到的内容列表
            query (str): 用户原始查询
            max_length (int): 触发总结的最大长度阈值

        Returns:
            str: 总结后的内容（如果未超过阈值则返回原内容）
        """
        # 计算总长度
        total_context = "\n\n".join(context_list)
        total_length = len(total_context)

        logger.info(f"检索内容总长度: {total_length} 字符")

        # 如果未超过阈值，直接返回
        if total_length <= max_length:
            logger.info(f"内容长度未超过阈值 ({max_length})，无需总结")
            return total_context

        # 需要总结
        logger.info(f"内容长度超过阈值，开始总结...")

        try:
            # 调用 LLM 进行总结
            summarized = self.call_llm_chain(
                ReaderRole.CONTEXT_SUMMARIZER,
                "",
                "context_summarization",
                system_format_dict={
                    "context": total_context,
                    "query": query
                }
            )

            logger.info(f"总结完成，压缩比: {len(summarized)}/{total_length} = {len(summarized)/total_length*100:.1f}%")
            return summarized

        except Exception as e:
            logger.error(f"总结上下文时出错: {e}")
            # 如果总结失败，返回截断的原始内容
            logger.warning(f"总结失败，返回截断的原始内容（前 {max_length} 字符）")
            return total_context[:max_length] + "\n\n[内容已截断...]"

    def _evaluate_retrieval_results(self, query: str, retrieved_context: str) -> Dict[str, Any]:
        """
        评估检索结果是否足够回答用户问题

        使用 LLM 评估当前检索到的内容是否足够，以及是否需要继续检索。

        Args:
            query (str): 用户原始查询
            retrieved_context (str): 已检索到的内容摘要

        Returns:
            Dict[str, Any]: 评估结果
                {
                    "continue": bool,  # 是否需要继续检索
                    "reason": str,  # 评估理由
                    "suggested_action": str  # 建议的下一步行动（工具名称）
                }
        """
        logger.info("正在评估检索结果...")

        try:
            # 调用评估 prompt
            response = self.call_llm_chain(
                ReaderRole.RETRIEVAL_EVALUATOR,
                "",
                "evaluation",
                system_format_dict={
                    "query": query,
                    "retrieved_summary": retrieved_context
                }
            )

            # 解析 JSON 响应
            evaluation = extract_data_from_LLM_res(response)

            logger.info(f"评估结果: continue={evaluation.get('continue')}, reason={evaluation.get('reason')}")

            return evaluation

        except Exception as e:
            logger.error(f"评估检索结果时出错: {e}")
            # 默认停止检索
            return {
                "continue": False,
                "reason": f"评估失败: {e}",
                "suggested_action": None
            }