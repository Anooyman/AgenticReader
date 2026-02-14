"""
SearchAgent Workflow 节点实现

包含所有 workflow 节点的实现逻辑
"""

from __future__ import annotations
from typing import Dict, TYPE_CHECKING
import logging
import json

from .state import SearchState
from .prompts import SearchRole
from .utils import extract_json_from_llm_response
from src.config.constants import ProcessingLimits

if TYPE_CHECKING:
    from .agent import SearchAgent

logger = logging.getLogger(__name__)


class SearchNodes:
    """SearchAgent Workflow 节点集合"""

    def __init__(self, agent: 'SearchAgent'):
        """
        Args:
            agent: SearchAgent 实例（依赖注入）
        """
        self.agent = agent

    # ========== 初始化节点 ==========

    async def initialize(self, state: SearchState) -> Dict:
        """初始化节点：验证输入，设置默认值"""
        logger.info("🔧 [Initialize] ========== SearchAgent 初始化 ==========")

        try:
            # 验证state
            self.agent.utils.validate_state(state)

            # 设置默认值
            if 'max_iterations' not in state:
                state['max_iterations'] = 3

            if 'current_iteration' not in state:
                state['current_iteration'] = 0

            # 初始化列表字段
            for field in ['thoughts', 'actions', 'observations', 'warnings']:
                if field not in state:
                    state[field] = []

            for field in ['search_engine_results', 'selected_urls', 'scraped_results', 'extracted_content', 'sources']:
                if field not in state:
                    state[field] = []

            # 日志输出
            logger.info(f"🔧 [Initialize] 用户查询: {state['query']}")
            logger.info(f"🔧 [Initialize] 最大迭代: {state['max_iterations']}")

            if 'target_urls' in state and state['target_urls']:
                logger.info(f"🔧 [Initialize] 指定URL: {state['target_urls']}")

            logger.info("✅ [Initialize] 初始化完成")
            return state

        except Exception as e:
            logger.error(f"❌ [Initialize] 初始化失败: {e}", exc_info=True)
            state['error'] = str(e)
            state['is_complete'] = True
            return state

    # ========== Use Case 分析节点 ==========

    async def analyze_query(self, state: SearchState) -> Dict:
        """分析查询并判断使用场景"""
        logger.info("🤔 [AnalyzeQuery] ========== 分析查询类型 ==========")

        try:
            query = state['query']
            target_urls = state.get('target_urls')

            # 如果用户已指定 use_case，直接使用
            if 'use_case' in state and state['use_case']:
                detected_use_case = state['use_case']
                reason = "用户手动指定"
                logger.info(f"✅ [AnalyzeQuery] 使用用户指定的场景: {detected_use_case}")
            else:
                # 自动检测
                detected_use_case, reason = self.agent.utils.auto_detect_use_case(query, target_urls)

            state['detected_use_case'] = detected_use_case
            state['use_case_reason'] = reason

            logger.info(f"🤔 [AnalyzeQuery] 检测结果:")
            logger.info(f"   - Use Case: {detected_use_case}")
            logger.info(f"   - 理由: {reason}")

            # 如果是 URL 分析模式，提取 URL
            if detected_use_case == "url_analysis":
                if not target_urls:
                    # 尝试从查询中提取URL
                    extracted_urls = self.agent.utils.extract_urls_from_text(query)
                    if extracted_urls:
                        state['target_urls'] = extracted_urls
                        logger.info(f"🤔 [AnalyzeQuery] 从查询中提取了 {len(extracted_urls)} 个URL")
                    else:
                        logger.warning("⚠️  [AnalyzeQuery] URL分析模式但未找到URL，切换到搜索模式")
                        state['detected_use_case'] = "search"
                        state['use_case_reason'] = "URL分析模式但未找到URL"

            return state

        except Exception as e:
            logger.error(f"❌ [AnalyzeQuery] 分析失败: {e}", exc_info=True)
            # 失败时默认使用搜索模式
            state['detected_use_case'] = "search"
            state['use_case_reason'] = f"分析失败，默认搜索模式: {str(e)}"
            return state

    # ========== Use Case 1: 搜索引擎查询节点 ==========

    async def web_search(self, state: SearchState) -> Dict:
        """搜索引擎查询节点"""
        logger.info("🔍 [WebSearch] ========== 搜索引擎查询 ==========")

        try:
            query = state['query']

            # 步骤1: 优化查询（可选）
            # 这里可以调用 LLM 优化查询，暂时直接使用原始查询
            search_query = query
            state['search_query'] = search_query

            logger.info(f"🔍 [WebSearch] 搜索查询: {search_query}")

            # 步骤2: 调用搜索引擎工具
            search_result = await self.agent.tools.web_search(
                query=search_query,
                max_results=10
            )

            if search_result.get('success'):
                results = search_result.get('results', [])
                state['search_engine_results'] = results

                logger.info(f"✅ [WebSearch] 获取到 {len(results)} 个搜索结果")

                # 记录observation
                state['observations'] = state.get('observations', []) + [
                    f"搜索到 {len(results)} 个结果"
                ]
            else:
                error_msg = search_result.get('error', '未知错误')
                logger.error(f"❌ [WebSearch] 搜索失败: {error_msg}")

                state['search_engine_results'] = []
                state['warnings'] = state.get('warnings', []) + [f"搜索失败: {error_msg}"]

            return state

        except Exception as e:
            logger.error(f"❌ [WebSearch] 搜索异常: {e}", exc_info=True)
            state['search_engine_results'] = []
            state['warnings'] = state.get('warnings', []) + [f"搜索异常: {str(e)}"]
            return state

    # ========== Use Case 1: URL筛选节点 ==========

    async def select_urls(self, state: SearchState) -> Dict:
        """从搜索结果中筛选相关URL"""
        logger.info("📋 [SelectURLs] ========== 筛选相关URL ==========")

        try:
            search_results = state.get('search_engine_results', [])

            if not search_results:
                logger.warning("⚠️  [SelectURLs] 没有搜索结果可供筛选")
                state['selected_urls'] = []
                return state

            # 步骤1: 使用 LLM 筛选 URL
            # 构建 prompt
            query = state['query']
            max_urls = 5  # 最多选择5个URL

            # 格式化搜索结果
            results_text = "\n".join([
                f"{idx}. {item['title']}\n   URL: {item['url']}\n   摘要: {item['snippet']}\n"
                for idx, item in enumerate(search_results, 1)
            ])

            prompt = SearchRole.URL_SELECTOR.format(
                query=query,
                search_results=results_text,
                max_urls=max_urls
            )

            logger.info("📋 [SelectURLs] 调用 LLM 筛选URL...")
            response = await self.agent.llm.async_call_llm_chain(
                role="",  # 使用空角色，prompt已经包含完整指令
                input_prompt=prompt,
                session_id="select_urls"
            )

            # 解析 JSON 响应
            try:
                # 使用工具函数从LLM响应中提取JSON
                selection_data = extract_json_from_llm_response(response)
                selected_items = selection_data.get('selected_urls', [])
                overall_reason = selection_data.get('overall_reason', '')

                # 提取 URL 列表
                selected_urls = [item['url'] for item in selected_items if 'url' in item]

                state['selected_urls'] = selected_urls
                state['selection_reason'] = overall_reason

                logger.info(f"✅ [SelectURLs] 筛选出 {len(selected_urls)} 个相关URL")
                for idx, item in enumerate(selected_items, 1):
                    logger.info(f"   {idx}. {item.get('url', '')} - {item.get('reason', '')}")

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"⚠️  [SelectURLs] JSON解析失败 ({e})，使用前5个URL")
                logger.debug(f"📋 [SelectURLs] 原始响应: {response[:500]}")
                state['selected_urls'] = [item['url'] for item in search_results[:max_urls]]
                state['selection_reason'] = "LLM响应解析失败，使用默认策略"

            return state

        except Exception as e:
            logger.error(f"❌ [SelectURLs] 筛选失败: {e}", exc_info=True)
            # 失败时使用前3个URL
            search_results = state.get('search_engine_results', [])
            state['selected_urls'] = [item['url'] for item in search_results[:3]]
            state['selection_reason'] = f"筛选失败，使用前3个URL: {str(e)}"
            return state

    # ========== 内容爬取节点（两种 use case 共用）==========

    async def scrape_content(self, state: SearchState) -> Dict:
        """爬取网页内容"""
        logger.info("🌐 [ScrapeContent] ========== 爬取网页内容 ==========")

        try:
            detected_use_case = state.get('detected_use_case', 'search')

            # 确定要爬取的 URL 列表
            if detected_use_case == "search":
                urls_to_scrape = state.get('selected_urls', [])
            else:  # url_analysis
                urls_to_scrape = state.get('target_urls', [])

            if not urls_to_scrape:
                logger.warning("⚠️  [ScrapeContent] 没有URL需要爬取")
                state['scraped_results'] = []
                return state

            logger.info(f"🌐 [ScrapeContent] 待爬取URL数: {len(urls_to_scrape)}")

            # 选择爬取方式：单个 vs 批量
            if len(urls_to_scrape) == 1:
                # 单个URL：使用 scrape_single_url
                url = urls_to_scrape[0]
                logger.info(f"🌐 [ScrapeContent] 单个URL爬取: {url}")

                result = await self.agent.tools.scrape_single_url(
                    url=url,
                    content_types=["html", "text", "json"],
                    timeout=30000
                )

                state['scraped_results'] = [result]

            else:
                # 多个URL：使用 scrape_batch_urls
                logger.info(f"🌐 [ScrapeContent] 批量爬取 {len(urls_to_scrape)} 个URL")

                batch_result = await self.agent.tools.scrape_batch_urls(
                    urls=urls_to_scrape,
                    content_types=["text"],  # 批量爬取默认只提取文本
                    concurrent_limit=3,
                    delay_between=2000
                )

                if batch_result.get('success'):
                    state['scraped_results'] = batch_result.get('results', [])

                    logger.info(f"✅ [ScrapeContent] 批量爬取完成")
                    logger.info(f"   - 成功: {batch_result.get('succeeded', 0)}")
                    logger.info(f"   - 失败: {batch_result.get('failed', 0)}")
                else:
                    state['scraped_results'] = []
                    error_msg = batch_result.get('error', '未知错误')
                    state['warnings'] = state.get('warnings', []) + [f"批量爬取失败: {error_msg}"]

            # 记录observation
            successful_count = sum(1 for r in state.get('scraped_results', []) if r.get('success'))
            state['observations'] = state.get('observations', []) + [
                f"爬取了 {len(urls_to_scrape)} 个URL，成功 {successful_count} 个"
            ]

            return state

        except Exception as e:
            logger.error(f"❌ [ScrapeContent] 爬取异常: {e}", exc_info=True)
            state['scraped_results'] = []
            state['warnings'] = state.get('warnings', []) + [f"爬取异常: {str(e)}"]
            return state

    # ========== Use Case 2: 内容量评估节点 ==========

    async def evaluate_content_size(self, state: SearchState) -> Dict:
        """评估内容量并决定处理策略"""
        logger.info("⚖️ [EvaluateSize] ========== 评估内容量 ==========")

        try:
            scraped_results = state.get('scraped_results', [])

            # 合并所有爬取的文本
            merged_text = self.agent.utils.merge_scraped_content(scraped_results)
            state['merged_text'] = merged_text

            # 计算内容大小
            size_metrics = self.agent.utils.calculate_content_size(merged_text)
            content_size = size_metrics['chars']
            state['content_size'] = content_size

            logger.info(f"⚖️ [EvaluateSize] 内容统计:")
            logger.info(f"   - 字符数: {size_metrics['chars']}")
            logger.info(f"   - 单词数: {size_metrics['words']}")
            logger.info(f"   - 估算tokens: {size_metrics['estimated_tokens']}")

            # 决定处理策略
            threshold = 5000  # 字符数阈值
            num_sources = len([r for r in scraped_results if r.get('success')])

            should_index, reason = self.agent.utils.should_index_content(
                content_size=content_size,
                threshold=threshold,
                num_sources=num_sources
            )

            if should_index:
                state['processing_strategy'] = "index_then_chat"
                state['should_call_indexing'] = True
                logger.info(f"⚖️ [EvaluateSize] 策略: 索引后对话")
                logger.info(f"⚖️ [EvaluateSize] 理由: {reason}")
            else:
                state['processing_strategy'] = "direct_chat"
                state['should_call_indexing'] = False
                logger.info(f"⚖️ [EvaluateSize] 策略: 直接对话")
                logger.info(f"⚖️ [EvaluateSize] 理由: {reason}")

            state['strategy_reason'] = reason

            # Use Case 2: 保存 URL 内容到 JSON 文件
            use_case = state.get('use_case', '')
            if use_case == 'url_analysis' and scraped_results:
                try:
                    # 获取第一个成功的结果（Use Case 2 通常只有一个 URL）
                    for result in scraped_results:
                        if result.get('success'):
                            url = result.get('url', '')
                            content = result.get('content', {})

                            # 保存内容
                            json_path = self.agent.utils.save_web_content(
                                url=url,
                                content=content,
                                metadata={
                                    "content_size": content_size,
                                    "processing_strategy": state['processing_strategy'],
                                    "strategy_reason": reason
                                }
                            )

                            # 将文件路径保存到 state 中，方便后续 IndexingAgent 使用
                            state['web_content_json'] = json_path

                            # 生成文档名（用于 IndexingAgent）
                            doc_name = self.agent.utils.generate_doc_name_from_url(url)
                            state['generated_doc_name'] = doc_name

                            logger.info(f"📄 [EvaluateSize] 生成文档名: {doc_name}")

                            break  # 只处理第一个成功的结果

                except Exception as save_error:
                    logger.warning(f"⚠️  [EvaluateSize] 保存 web 内容失败: {save_error}")

            return state

        except Exception as e:
            logger.error(f"❌ [EvaluateSize] 评估失败: {e}", exc_info=True)
            # 失败时默认直接对话
            state['processing_strategy'] = "direct_chat"
            state['should_call_indexing'] = False
            state['strategy_reason'] = f"评估失败，默认直接对话: {str(e)}"
            return state

    # ========== 内容提取节点 ==========

    async def extract_and_merge(self, state: SearchState) -> Dict:
        """提取并合并爬取的内容"""
        logger.info("📝 [ExtractMerge] ========== 提取并合并内容 ==========")

        try:
            scraped_results = state.get('scraped_results', [])

            extracted_content = []
            sources = []

            for result in scraped_results:
                if not result.get('success'):
                    continue

                url = result.get('url', '')
                content = result.get('content', {})

                # 提取文本
                text = content.get('text', '')
                html = content.get('html', '')
                json_data = content.get('json', {})

                if text and text.strip():
                    extracted_content.append({
                        "url": url,
                        "text": text,
                        "html": html,
                        "json": json_data
                    })

                    sources.append(url)

            state['extracted_content'] = extracted_content
            state['sources'] = sources

            logger.info(f"✅ [ExtractMerge] 提取了 {len(extracted_content)} 个内容片段")

            # 对于 Use Case 1（搜索引擎检索），保存到缓存
            use_case = state.get('use_case', '')
            if use_case == 'search' and extracted_content:
                try:
                    query = state.get('query', '')
                    # 构建缓存数据格式
                    cache_sources = []
                    for item in extracted_content:
                        cache_sources.append({
                            "url": item.get('url', ''),
                            "title": item.get('url', '').split('/')[-1],  # 简单从URL提取标题
                            "content": {
                                "text": item.get('text', ''),
                                "html": item.get('html', ''),
                                "json": item.get('json', {})
                            }
                        })

                    # 保存缓存（答案稍后在 format_answer 节点添加）
                    self.agent.utils.save_search_cache(
                        query=query,
                        sources=cache_sources,
                        answer=None  # 答案稍后更新
                    )
                except Exception as cache_error:
                    logger.warning(f"⚠️  [ExtractMerge] 保存缓存失败: {cache_error}")

            return state

        except Exception as e:
            logger.error(f"❌ [ExtractMerge] 提取失败: {e}", exc_info=True)
            state['extracted_content'] = []
            state['sources'] = []
            return state

    # ========== 完整性评估节点 ==========

    async def evaluate_completeness(self, state: SearchState) -> Dict:
        """评估检索结果的完整性"""
        logger.info("⚖️ [Evaluate] ========== 评估完整性 ==========")

        try:
            current_iteration = state.get('current_iteration', 0)
            max_iterations = state.get('max_iterations', 3)
            extracted_content = state.get('extracted_content', [])

            logger.info(f"⚖️ [Evaluate] 迭代进度: {current_iteration + 1}/{max_iterations}")
            logger.info(f"⚖️ [Evaluate] 已提取内容数: {len(extracted_content)}")

            # 简单策略：如果有内容就认为完整
            if len(extracted_content) > 0:
                state['is_complete'] = True
                logger.info("✅ [Evaluate] 评估完成：已获取足够内容")
            elif current_iteration >= max_iterations - 1:
                # 达到最大迭代次数
                state['is_complete'] = True
                logger.warning("⚠️  [Evaluate] 达到最大迭代次数，强制完成")
            else:
                state['is_complete'] = False
                logger.info("🔄 [Evaluate] 内容不足，继续检索")

            # 更新迭代计数
            state['current_iteration'] = current_iteration + 1

            return state

        except Exception as e:
            logger.error(f"❌ [Evaluate] 评估失败: {e}", exc_info=True)
            state['is_complete'] = True  # 失败时强制完成
            return state

    # ========== 答案生成节点 ==========

    async def format_answer(self, state: SearchState) -> Dict:
        """生成最终答案"""
        logger.info("🎯 [FormatAnswer] ========== 生成最终答案 ==========")

        try:
            query = state['query']
            extracted_content = state.get('extracted_content', [])
            sources = state.get('sources', [])
            detected_use_case = state.get('detected_use_case', 'search')

            if not extracted_content:
                state['final_answer'] = "抱歉，未能获取到相关内容。请尝试调整查询或检查网络连接。"
                logger.warning("⚠️  [FormatAnswer] 无内容可用，返回默认答案")
                return state

            # 合并内容
            merged_content = "\n\n".join([
                f"=== 来源: {item['url']} ===\n{item['text'][:2000]}"  # 每个来源最多2000字符
                for item in extracted_content
            ])

            # 构建 prompt
            prompt = SearchRole.CONTENT_SUMMARIZER.format(
                query=query,
                scraped_content=merged_content
            )

            logger.info("🎯 [FormatAnswer] 调用 LLM 生成答案...")
            final_answer = await self.agent.llm.async_call_llm_chain(
                role="",
                input_prompt=prompt,
                session_id="format_answer"
            )

            # 添加信息来源
            if sources:
                final_answer += "\n\n## 信息来源\n"
                for idx, source_url in enumerate(sources, 1):
                    final_answer += f"{idx}. {source_url}\n"

            state['final_answer'] = final_answer

            logger.info(f"✅ [FormatAnswer] 答案生成完成")
            logger.info(f"   - 答案长度: {len(final_answer)} 字符")
            logger.info(f"   - 来源数: {len(sources)}")

            # 对于 Use Case 1，更新缓存添加答案
            use_case = state.get('use_case', '')
            if use_case == 'search' and extracted_content:
                try:
                    # 构建完整的缓存数据
                    cache_sources = []
                    for item in extracted_content:
                        cache_sources.append({
                            "url": item.get('url', ''),
                            "title": item.get('url', '').split('/')[-1],
                            "content": {
                                "text": item.get('text', ''),
                                "html": item.get('html', ''),
                                "json": item.get('json', {})
                            }
                        })

                    # 保存完整缓存（包含答案）
                    self.agent.utils.save_search_cache(
                        query=query,
                        sources=cache_sources,
                        answer=final_answer
                    )
                    logger.info("💾 [FormatAnswer] 搜索结果已保存到缓存")
                except Exception as cache_error:
                    logger.warning(f"⚠️  [FormatAnswer] 更新缓存失败: {cache_error}")

            return state

        except Exception as e:
            logger.error(f"❌ [FormatAnswer] 生成答案失败: {e}", exc_info=True)
            state['final_answer'] = f"生成答案时出错: {str(e)}"
            return state

    # ========== 条件路由节点 ==========

    def should_continue(self, state: SearchState) -> str:
        """判断是否继续检索"""
        is_complete = state.get('is_complete', False)

        if is_complete:
            logger.info("✅ [ShouldContinue] 检索完成，生成答案")
            return "format"

        logger.info("🔄 [ShouldContinue] 继续检索")
        return "continue"

    def route_by_use_case(self, state: SearchState) -> str:
        """根据 use case 路由到不同分支"""
        detected_use_case = state.get('detected_use_case', 'search')

        if detected_use_case == "search":
            logger.info("🔍 [Route] 路由到: 搜索引擎模式")
            return "search"
        else:  # url_analysis
            logger.info("📄 [Route] 路由到: URL分析模式")
            return "url_analysis"
