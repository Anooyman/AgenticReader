"""
SearchAgent 工具实现

封装 MCP 工具调用：
- web_scraper MCP: 网页爬取
- DuckDuckGo MCP: 搜索引擎（或其他搜索API）
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List, Any, Optional
import logging
import json

if TYPE_CHECKING:
    from .agent import SearchAgent

logger = logging.getLogger(__name__)


class SearchTools:
    """SearchAgent 工具方法集合"""

    def __init__(self, agent: 'SearchAgent'):
        """
        Args:
            agent: SearchAgent 实例（依赖注入）
        """
        self.agent = agent

    # ========== 辅助方法 ==========

    def _parse_text_search_results(self, text: str) -> Dict:
        """
        解析文本格式的搜索结果

        DuckDuckGo MCP 返回格式:
        Found 10 search results:

        1. Title
           URL: https://...
           Summary: ...

        2. Title
           URL: https://...
           Summary: ...

        Args:
            text: 原始文本

        Returns:
            {"results": [{"title": str, "url": str, "snippet": str}, ...]}
        """
        import re

        results = []

        # 使用正则提取每个结果块
        # 匹配模式: 数字. 标题\n   URL: ...\n   Summary: ...
        pattern = r'(\d+)\.\s+(.+?)\s+URL:\s+(\S+)\s+Summary:\s+(.+?)(?=\n\d+\.|$)'

        matches = re.findall(pattern, text, re.DOTALL)

        for match in matches:
            idx, title, url, summary = match
            results.append({
                "title": title.strip(),
                "url": url.strip(),
                "snippet": summary.strip()
            })

        logger.info(f"📝 [TextParser] 从文本中解析出 {len(results)} 个结果")

        return {"results": results}

    # ========== 搜索引擎工具 ==========

    async def web_search(self, query: str, max_results: int = 10) -> Dict:
        """
        使用搜索引擎查找相关网页

        调用 DuckDuckGo MCP（或其他搜索API）

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            标准格式响应：
            {
                "success": bool,
                "results": [{"title": str, "url": str, "snippet": str}, ...],
                "total": int,
                "error": str (如果失败)
            }
        """
        logger.info(f"🔍 [Tool:web_search] 搜索引擎查询: {query}")
        logger.info(f"🔍 [Tool:web_search] 最大结果数: {max_results}")

        try:
            # 初始化 MCP client（DuckDuckGo 或其他搜索服务）
            mcp_client = await self.agent.utils.init_mcp_client("duckduckgo")

            if not mcp_client:
                logger.error("❌ [Tool:web_search] 搜索引擎 MCP client 未初始化")
                return {
                    "success": False,
                    "results": [],
                    "total": 0,
                    "error": "搜索引擎服务不可用"
                }

            # 调用 MCP 工具
            logger.info("🔍 [Tool:web_search] 调用 DuckDuckGo MCP...")
            result = await mcp_client.call_tool(
                tool_name="search",  # DuckDuckGo MCP 的工具名称
                arguments={
                    "query": query,
                    "max_results": max_results
                }
            )

            # 解析结果
            if result and isinstance(result, list) and len(result) > 0:
                # MCP 返回 TextContent 对象，直接访问 .text 属性
                result_text = result[0].text

                # 调试：输出原始返回内容（使用 INFO 级别确保可见）
                logger.info(f"🔍 [Tool:web_search] DuckDuckGo 原始返回（前500字符）:")
                logger.info(f"   {result_text[:500]}")
                if len(result_text) > 500:
                    logger.info(f"   ... (共 {len(result_text)} 字符)")

                # 尝试解析 JSON
                try:
                    parsed_result = json.loads(result_text)
                    logger.debug(f"🔍 [Tool:web_search] 解析后的 JSON keys: {list(parsed_result.keys())}")
                except json.JSONDecodeError as e:
                    # 如果不是 JSON，尝试文本解析
                    #logger.warning(f"⚠️  [Tool:web_search] JSON 解析失败: {e}")
                    logger.info(f"🔍 [Tool:web_search] 尝试使用文本解析器...")
                    parsed_result = self._parse_text_search_results(result_text)

                # 格式化结果 - 尝试多种可能的 key
                search_results = []

                # 尝试不同的结果字段
                if "results" in parsed_result:
                    search_results = parsed_result["results"]
                elif "data" in parsed_result:
                    search_results = parsed_result["data"]
                elif "items" in parsed_result:
                    search_results = parsed_result["items"]
                elif isinstance(parsed_result, list):
                    # 如果整个结果就是一个列表
                    search_results = parsed_result
                else:
                    # 如果是单个对象，包装成列表
                    logger.warning(f"⚠️  [Tool:web_search] 未识别的结果格式，keys: {list(parsed_result.keys())}")
                    search_results = []

                logger.info(f"🔍 [Tool:web_search] 提取到 {len(search_results)} 个原始结果")

                # 使用 utils 统一格式化
                formatted_results = self.agent.utils.format_search_results(search_results)

                logger.info(f"✅ [Tool:web_search] 获取到 {len(formatted_results)} 个结果")

                # 显示结果预览
                for idx, item in enumerate(formatted_results[:3], 1):
                    logger.info(f"   {idx}. {item['title'][:50]}... ({item['url']})")

                return {
                    "success": True,
                    "results": formatted_results,
                    "total": len(formatted_results)
                }
            else:
                logger.warning("⚠️  [Tool:web_search] 搜索引擎返回空结果")
                return {
                    "success": False,
                    "results": [],
                    "total": 0,
                    "error": "未找到相关结果"
                }

        except Exception as e:
            logger.error(f"❌ [Tool:web_search] 搜索失败: {e}", exc_info=True)
            return {
                "success": False,
                "results": [],
                "total": 0,
                "error": str(e)
            }

    # ========== 网页爬取工具 ==========

    async def scrape_single_url(
        self,
        url: str,
        content_types: Optional[List[str]] = None,
        wait_for: Optional[str] = None,
        timeout: int = 30000
    ) -> Dict:
        """
        爬取单个网页内容

        调用 web_scraper MCP 的 scrape_url 工具

        Args:
            url: 目标URL
            content_types: 内容类型列表 ["html", "text", "json", "screenshot"]
            wait_for: CSS选择器（等待动态加载）
            timeout: 超时时间（毫秒）

        Returns:
            标准格式响应：
            {
                "success": bool,
                "url": str,
                "content": {"html": str, "text": str, "json": dict},
                "files": [str],
                "metadata": {"timestamp": str, "duration_ms": int},
                "error": str (如果失败)
            }
        """
        logger.info(f"🌐 [Tool:scrape_single_url] 爬取URL: {url}")

        # 默认内容类型
        if content_types is None:
            content_types = ["html", "text"]

        logger.info(f"🌐 [Tool:scrape_single_url] 内容类型: {content_types}")

        try:
            # 验证URL
            if not self.agent.utils.is_valid_url(url):
                logger.error(f"❌ [Tool:scrape_single_url] 无效的URL: {url}")
                return {
                    "success": False,
                    "url": url,
                    "content": {},
                    "files": [],
                    "error": "无效的URL格式"
                }

            # 初始化 web_scraper MCP client
            mcp_client = await self.agent.utils.init_mcp_client("web_scraper")

            if not mcp_client:
                logger.error("❌ [Tool:scrape_single_url] web_scraper MCP client 未初始化")
                return {
                    "success": False,
                    "url": url,
                    "content": {},
                    "files": [],
                    "error": "网页爬取服务不可用"
                }

            # 构建参数
            tool_args = {
                "url": url,
                "content_types": content_types,
                "timeout": timeout
            }

            if wait_for:
                tool_args["wait_for"] = wait_for

            # 调用 MCP 工具
            logger.info("🌐 [Tool:scrape_single_url] 调用 web_scraper MCP...")
            result = await mcp_client.call_tool(
                tool_name="scrape_url",
                arguments=tool_args
            )

            # 解析结果
            if result and isinstance(result, list) and len(result) > 0:
                # result[0] 是 TextContent 对象，直接访问 .text 属性
                result_text = result[0].text

                # 解析 JSON
                try:
                    parsed_result = json.loads(result_text)
                except json.JSONDecodeError:
                    logger.error("❌ [Tool:scrape_single_url] 解析MCP结果失败")
                    return {
                        "success": False,
                        "url": url,
                        "content": {},
                        "files": [],
                        "error": "解析爬取结果失败"
                    }

                # 检查成功标志
                if parsed_result.get("success"):
                    data = parsed_result.get("data", {})
                    content = data.get("content", {})

                    # 提取文本长度用于日志
                    text_length = len(content.get("text", ""))
                    html_length = len(content.get("html", ""))

                    logger.info(f"✅ [Tool:scrape_single_url] 爬取成功")
                    logger.info(f"   - 文本长度: {text_length} 字符")
                    logger.info(f"   - HTML长度: {html_length} 字符")
                    logger.info(f"   - 保存文件: {len(data.get('files', []))} 个")

                    return {
                        "success": True,
                        "url": data.get("url", url),
                        "content": content,
                        "files": data.get("files", []),
                        "metadata": data.get("metadata", {})
                    }
                else:
                    error_msg = parsed_result.get("error", "未知错误")
                    logger.error(f"❌ [Tool:scrape_single_url] 爬取失败: {error_msg}")
                    return {
                        "success": False,
                        "url": url,
                        "content": {},
                        "files": [],
                        "error": error_msg
                    }
            else:
                logger.error("❌ [Tool:scrape_single_url] MCP 返回空结果")
                return {
                    "success": False,
                    "url": url,
                    "content": {},
                    "files": [],
                    "error": "爬取服务返回空结果"
                }

        except Exception as e:
            logger.error(f"❌ [Tool:scrape_single_url] 爬取失败: {e}", exc_info=True)
            return {
                "success": False,
                "url": url,
                "content": {},
                "files": [],
                "error": str(e)
            }

    async def scrape_batch_urls(
        self,
        urls: List[str],
        content_types: Optional[List[str]] = None,
        concurrent_limit: int = 3,
        delay_between: int = 2000
    ) -> Dict:
        """
        批量爬取多个网页

        调用 web_scraper MCP 的 scrape_batch 工具

        Args:
            urls: URL列表
            content_types: 内容类型
            concurrent_limit: 并发数限制
            delay_between: 请求间延迟（毫秒）

        Returns:
            标准格式响应：
            {
                "success": bool,
                "total": int,
                "succeeded": int,
                "failed": int,
                "results": [
                    {"url": str, "success": bool, "content": {...}, "files": [...], "error": str},
                    ...
                ]
            }
        """
        logger.info(f"🌐 [Tool:scrape_batch_urls] 批量爬取 {len(urls)} 个URL")
        logger.info(f"🌐 [Tool:scrape_batch_urls] 并发限制: {concurrent_limit}, 延迟: {delay_between}ms")

        # 默认内容类型
        if content_types is None:
            content_types = ["text"]  # 批量爬取默认只提取文本

        try:
            # 验证URL列表
            valid_urls = [url for url in urls if self.agent.utils.is_valid_url(url)]

            if len(valid_urls) == 0:
                logger.error("❌ [Tool:scrape_batch_urls] 没有有效的URL")
                return {
                    "success": False,
                    "total": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "results": [],
                    "error": "没有有效的URL"
                }

            if len(valid_urls) < len(urls):
                logger.warning(f"⚠️  [Tool:scrape_batch_urls] 过滤了 {len(urls) - len(valid_urls)} 个无效URL")

            # 初始化 MCP client
            mcp_client = await self.agent.utils.init_mcp_client("web_scraper")

            if not mcp_client:
                logger.error("❌ [Tool:scrape_batch_urls] web_scraper MCP client 未初始化")
                return {
                    "success": False,
                    "total": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "results": [],
                    "error": "网页爬取服务不可用"
                }

            # 调用 MCP 工具
            logger.info("🌐 [Tool:scrape_batch_urls] 调用 web_scraper MCP 批量爬取...")
            result = await mcp_client.call_tool(
                tool_name="scrape_batch",
                arguments={
                    "urls": valid_urls,
                    "content_types": content_types,
                    "concurrent_limit": concurrent_limit,
                    "delay_between": delay_between
                }
            )

            # 解析结果
            if result and isinstance(result, list) and len(result) > 0:
                # result[0] 是 TextContent 对象，直接访问 .text 属性
                result_text = result[0].text

                try:
                    parsed_result = json.loads(result_text)
                except json.JSONDecodeError:
                    logger.error("❌ [Tool:scrape_batch_urls] 解析MCP结果失败")
                    return {
                        "success": False,
                        "total": 0,
                        "succeeded": 0,
                        "failed": 0,
                        "results": [],
                        "error": "解析批量爬取结果失败"
                    }

                # 提取统计信息
                data = parsed_result.get("data", {})
                total = data.get("total", 0)
                succeeded = data.get("succeeded", 0)
                failed = data.get("failed", 0)
                results = data.get("results", [])

                logger.info(f"✅ [Tool:scrape_batch_urls] 批量爬取完成")
                logger.info(f"   - 总数: {total}, 成功: {succeeded}, 失败: {failed}")

                # 显示成功的结果预览
                successful_results = [r for r in results if r.get("success")]
                for idx, item in enumerate(successful_results[:3], 1):
                    url = item.get("url", "")
                    logger.info(f"   ✓ {idx}. {url}")

                return {
                    "success": True,
                    "total": total,
                    "succeeded": succeeded,
                    "failed": failed,
                    "results": results
                }
            else:
                logger.error("❌ [Tool:scrape_batch_urls] MCP 返回空结果")
                return {
                    "success": False,
                    "total": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "results": [],
                    "error": "批量爬取服务返回空结果"
                }

        except Exception as e:
            logger.error(f"❌ [Tool:scrape_batch_urls] 批量爬取失败: {e}", exc_info=True)
            return {
                "success": False,
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "results": [],
                "error": str(e)
            }

    # ========== 资源下载工具（可选）==========

    async def download_resources(
        self,
        url: str,
        resource_types: Optional[List[str]] = None,
        selector: Optional[str] = None,
        max_files: int = 50
    ) -> Dict:
        """
        从网页下载资源文件

        调用 web_scraper MCP 的 download_resources 工具

        Args:
            url: 目标URL
            resource_types: 资源类型 ["images", "pdfs", "videos"]
            selector: CSS选择器
            max_files: 最大下载数量

        Returns:
            标准格式响应：
            {
                "success": bool,
                "url": str,
                "downloaded_files": [str],
                "count": int,
                "metadata": {...},
                "error": str (如果失败)
            }
        """
        logger.info(f"📥 [Tool:download_resources] 下载资源: {url}")

        # 默认资源类型
        if resource_types is None:
            resource_types = ["images"]

        logger.info(f"📥 [Tool:download_resources] 资源类型: {resource_types}, 最大数量: {max_files}")

        try:
            # 验证URL
            if not self.agent.utils.is_valid_url(url):
                logger.error(f"❌ [Tool:download_resources] 无效的URL: {url}")
                return {
                    "success": False,
                    "url": url,
                    "downloaded_files": [],
                    "count": 0,
                    "error": "无效的URL格式"
                }

            # 初始化 MCP client
            mcp_client = await self.agent.utils.init_mcp_client("web_scraper")

            if not mcp_client:
                logger.error("❌ [Tool:download_resources] web_scraper MCP client 未初始化")
                return {
                    "success": False,
                    "url": url,
                    "downloaded_files": [],
                    "count": 0,
                    "error": "资源下载服务不可用"
                }

            # 构建参数
            tool_args = {
                "url": url,
                "resource_types": resource_types,
                "max_files": max_files
            }

            if selector:
                tool_args["selector"] = selector

            # 调用 MCP 工具
            logger.info("📥 [Tool:download_resources] 调用 web_scraper MCP...")
            result = await mcp_client.call_tool(
                tool_name="download_resources",
                arguments=tool_args
            )

            # 解析结果（与 scrape_single_url 类似的处理逻辑）
            if result and isinstance(result, list) and len(result) > 0:
                # result[0] 是 TextContent 对象，直接访问 .text 属性
                result_text = result[0].text

                try:
                    parsed_result = json.loads(result_text)
                except json.JSONDecodeError:
                    logger.error("❌ [Tool:download_resources] 解析MCP结果失败")
                    return {
                        "success": False,
                        "url": url,
                        "downloaded_files": [],
                        "count": 0,
                        "error": "解析下载结果失败"
                    }

                if parsed_result.get("success"):
                    data = parsed_result.get("data", {})
                    downloaded_files = data.get("downloaded_files", [])
                    count = data.get("count", 0)

                    logger.info(f"✅ [Tool:download_resources] 下载成功: {count} 个文件")

                    return {
                        "success": True,
                        "url": data.get("url", url),
                        "downloaded_files": downloaded_files,
                        "count": count,
                        "metadata": data.get("metadata", {})
                    }
                else:
                    error_msg = parsed_result.get("error", "未知错误")
                    logger.error(f"❌ [Tool:download_resources] 下载失败: {error_msg}")
                    return {
                        "success": False,
                        "url": url,
                        "downloaded_files": [],
                        "count": 0,
                        "error": error_msg
                    }
            else:
                logger.error("❌ [Tool:download_resources] MCP 返回空结果")
                return {
                    "success": False,
                    "url": url,
                    "downloaded_files": [],
                    "count": 0,
                    "error": "资源下载服务返回空结果"
                }

        except Exception as e:
            logger.error(f"❌ [Tool:download_resources] 下载失败: {e}", exc_info=True)
            return {
                "success": False,
                "url": url,
                "downloaded_files": [],
                "count": 0,
                "error": str(e)
            }
