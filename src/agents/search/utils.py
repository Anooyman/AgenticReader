"""
SearchAgent 辅助工具函数

提供：
- MCP Client 初始化和管理
- 内容量判断
- URL 验证
- 数据格式化
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List, Optional
import asyncio
import logging
import re
import json
from urllib.parse import urlparse
from contextlib import AsyncExitStack

if TYPE_CHECKING:
    from .agent import SearchAgent

logger = logging.getLogger(__name__)


# ========== JSON 提取辅助函数 ==========

def extract_json_from_llm_response(response: str) -> Dict:
    """
    从LLM响应中提取JSON对象

    支持以下格式：
    1. 纯JSON: {"key": "value"}
    2. Markdown代码块: ```json\n{"key": "value"}\n```
    3. 带说明的JSON: Some text\n```json\n{"key": "value"}\n```\nMore text

    Args:
        response: LLM响应文本

    Returns:
        解析后的JSON字典

    Raises:
        json.JSONDecodeError: JSON解析失败
    """
    json_text = response.strip()

    # 如果包含markdown代码块，提取JSON部分
    if "```json" in json_text:
        # 提取 ```json 和 ``` 之间的内容
        start = json_text.find("```json") + 7
        end = json_text.find("```", start)
        if end != -1:
            json_text = json_text[start:end].strip()
    elif "```" in json_text:
        # 提取第一个代码块
        start = json_text.find("```") + 3
        # 跳过可能的语言标识符（如json, python等）
        newline_pos = json_text.find("\n", start)
        if newline_pos != -1:
            start = newline_pos + 1
        end = json_text.find("```", start)
        if end != -1:
            json_text = json_text[start:end].strip()

    # 解析JSON
    return json.loads(json_text)


class SimpleMCPClient:
    """
    简化的 MCP Client，用于直接调用 MCP 工具
    不依赖 LLMBase，只负责工具调用
    """

    # MCP RPC 往返（session.initialize() / session.call_tool()）没有自带
    # 超时——工具参数里的 timeout（如 scrape_url 的 30000ms）只约束 Playwright
    # 内部的 page.goto 等待，管不到 MCP 子进程本身卡死/无响应的情况（比如
    # 子进程崩溃后 stdio 管道悬空、Playwright 浏览器进程僵死）。这里的
    # 硬上限就是补这道口子：真实场景下 job_runner 依赖 subprocess 被 kill
    # 兜底超时，一旦改成同进程直接调用（ai-research-pipeline 合并计划），
    # 这层 subprocess 保险会消失，必须在这里显式补上，否则一次卡死会拖垂
    # 整条任务车道。
    INITIALIZE_TIMEOUT = 30
    CALL_TOOL_TIMEOUT = 90

    def __init__(self, service_name: str, config: Dict):
        """
        初始化简化的 MCP Client

        Args:
            service_name: 服务名称
            config: MCP 服务配置
        """
        self.service_name = service_name
        self.config = config
        self.session = None
        self.exit_stack = AsyncExitStack()

    async def initialize(self):
        """初始化 MCP 连接"""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            connection_type = self.config.get("type", "stdio")

            if connection_type == "stdio":
                server_params = StdioServerParameters(
                    command=self.config.get("command"),
                    args=self.config.get("args", []),
                    env=self.config.get("env", {}),
                )

                stdio_transport = await self.exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                read_stream, write_stream = stdio_transport

                self.session = await self.exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )

                await asyncio.wait_for(
                    self.session.initialize(), timeout=self.INITIALIZE_TIMEOUT
                )
                logger.info(f"✅ [SimpleMCP] {self.service_name} session 初始化成功")

            else:
                logger.error(f"❌ [SimpleMCP] 不支持的连接类型: {connection_type}")
                raise ValueError(f"不支持的连接类型: {connection_type}")

        except asyncio.TimeoutError:
            logger.error(
                f"❌ [SimpleMCP] {self.service_name} 初始化超时"
                f"（>{self.INITIALIZE_TIMEOUT}s，MCP 子进程可能未正常响应）"
            )
            raise
        except Exception as e:
            logger.error(f"❌ [SimpleMCP] 初始化失败: {e}", exc_info=True)
            raise

    async def call_tool(self, tool_name: str, arguments: Dict) -> List:
        """
        调用 MCP 工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            工具调用结果
        """
        if not self.session:
            raise RuntimeError("MCP session 未初始化")

        try:
            result = await asyncio.wait_for(
                self.session.call_tool(tool_name, arguments),
                timeout=self.CALL_TOOL_TIMEOUT,
            )

            # 提取内容
            if hasattr(result, 'content') and result.content:
                return result.content

            return []

        except asyncio.TimeoutError:
            logger.error(
                f"❌ [SimpleMCP] 调用工具 {tool_name} 超时"
                f"（>{self.CALL_TOOL_TIMEOUT}s，MCP 子进程可能卡死）"
            )
            raise
        except Exception as e:
            logger.error(f"❌ [SimpleMCP] 调用工具 {tool_name} 失败: {e}", exc_info=True)
            raise

    async def disconnect(self):
        """断开连接"""
        try:
            await self.exit_stack.aclose()
            logger.info(f"✅ [SimpleMCP] {self.service_name} 连接已关闭")
        except RuntimeError as e:
            # 静默忽略 cancel scope 在不同任务中的错误（资源已正确清理）
            error_msg = str(e).lower()
            if "cancel scope" in error_msg or "different task" in error_msg:
                logger.debug(f"[SimpleMCP] {self.service_name} 跨任务清理完成（正常）")
            else:
                logger.warning(f"⚠️  [SimpleMCP] 关闭连接时出错: {e}")
        except Exception as e:
            logger.warning(f"⚠️  [SimpleMCP] 关闭连接时出错: {e}")


class SearchUtils:
    """SearchAgent 辅助工具类"""

    def __init__(self, agent: 'SearchAgent'):
        """
        Args:
            agent: SearchAgent 实例（依赖注入）
        """
        self.agent = agent
        self.mcp_clients: Dict[str, any] = {}  # MCP client 缓存

    # ========== MCP Client 管理 ==========

    async def init_mcp_client(self, service_name: str) -> Optional[any]:
        """
        初始化并缓存 MCP Client（使用简化版本，直接调用 MCP 工具）

        Args:
            service_name: MCP 服务名称（"web_scraper" 或 "duckduckgo"）

        Returns:
            SimpleMCPClient 实例，失败返回 None
        """
        # 检查缓存
        if service_name in self.mcp_clients:
            logger.info(f"🔌 [MCP] 复用已有的 {service_name} client")
            return self.mcp_clients[service_name]

        try:
            from src.config.settings import MCP_CONFIG

            # 获取配置
            config = MCP_CONFIG.get(service_name)
            if not config:
                logger.error(f"❌ [MCP] 未找到 {service_name} 的配置")
                return None

            logger.info(f"🔌 [MCP] 初始化 {service_name} client...")

            # 创建简化的 MCP client
            client = SimpleMCPClient(
                service_name=service_name,
                config=config
            )

            # 初始化连接
            await client.initialize()

            # 缓存
            self.mcp_clients[service_name] = client
            logger.info(f"✅ [MCP] {service_name} client 初始化成功")

            return client

        except Exception as e:
            logger.error(f"❌ [MCP] 初始化 {service_name} client 失败: {e}", exc_info=True)
            return None

    async def cleanup_mcp_clients(self):
        """清理所有 MCP clients"""
        for service_name, client in self.mcp_clients.items():
            try:
                if hasattr(client, 'disconnect'):
                    await client.disconnect()
                logger.info(f"🔌 [MCP] {service_name} client 已断开")
            except Exception as e:
                logger.warning(f"⚠️  [MCP] 断开 {service_name} client 时出错: {e}")

        self.mcp_clients.clear()

    # ========== URL 验证 ==========

    @staticmethod
    def is_valid_url(url: str) -> bool:
        """
        验证URL是否合法

        Args:
            url: 待验证的URL字符串

        Returns:
            是否为合法URL
        """
        if not url or not isinstance(url, str):
            return False

        try:
            result = urlparse(url.strip())
            # 必须有scheme (http/https) 和 netloc (域名)
            return all([result.scheme in ['http', 'https'], result.netloc])
        except Exception:
            return False

    @staticmethod
    def extract_urls_from_text(text: str) -> List[str]:
        """
        从文本中提取所有URL

        Args:
            text: 输入文本

        Returns:
            URL列表
        """
        # URL正则表达式
        url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
        urls = re.findall(url_pattern, text)

        # 验证并去重
        valid_urls = []
        seen = set()

        for url in urls:
            if SearchUtils.is_valid_url(url) and url not in seen:
                valid_urls.append(url)
                seen.add(url)

        return valid_urls

    @staticmethod
    def normalize_url(url: str) -> str:
        """
        标准化URL（去除末尾斜杠、查询参数等）

        Args:
            url: 原始URL

        Returns:
            标准化后的URL
        """
        url = url.strip()

        # 去除末尾斜杠
        if url.endswith('/'):
            url = url[:-1]

        return url

    # ========== 内容量判断 ==========

    @staticmethod
    def calculate_content_size(text: str) -> Dict[str, int]:
        """
        计算文本内容的大小指标

        Args:
            text: 文本内容

        Returns:
            包含多个指标的字典：
            {
                "chars": 字符数,
                "words": 单词数（中文按字符，英文按空格分割）,
                "estimated_tokens": 估算的token数
            }
        """
        if not text:
            return {"chars": 0, "words": 0, "estimated_tokens": 0}

        chars = len(text)

        # 简单的单词统计（中文每个字算一个词，英文按空格分割）
        # 检测是否包含中文
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'\b[a-zA-Z]+\b', text))

        words = chinese_chars + english_words

        # Token估算（粗略估计：中文1字=1token，英文1词=1.3token）
        estimated_tokens = chinese_chars + int(english_words * 1.3)

        return {
            "chars": chars,
            "words": words,
            "estimated_tokens": estimated_tokens
        }

    @staticmethod
    def should_index_content(
        content_size: int,
        threshold: int = 5000,
        num_sources: int = 1
    ) -> tuple[bool, str]:
        """
        判断内容是否应该索引

        Args:
            content_size: 内容字符数
            threshold: 字符数阈值（默认5000）
            num_sources: 来源数量

        Returns:
            (是否应该索引, 理由)
        """
        # 策略1: 内容量超过阈值
        if content_size >= threshold:
            return True, f"内容量大 ({content_size} 字符 ≥ {threshold} 阈值)"

        # 策略2: 多源内容（超过3个来源）
        if num_sources > 3:
            return True, f"多源内容 ({num_sources} 个来源 > 3)"

        # 策略3: 接近阈值（80%以上）
        if content_size >= threshold * 0.8:
            return True, f"接近阈值 ({content_size} 字符 ≥ {threshold * 0.8})"

        # 默认：直接对话
        return False, f"内容量小 ({content_size} 字符 < {threshold})"

    # ========== 数据格式化 ==========

    @staticmethod
    def format_search_results(raw_results: List[Dict]) -> List[Dict]:
        """
        格式化搜索引擎结果为统一格式

        Args:
            raw_results: 原始搜索结果

        Returns:
            格式化后的结果列表
            [{"title": str, "url": str, "snippet": str}, ...]
        """
        formatted = []

        for item in raw_results:
            # 提取关键字段（兼容不同搜索引擎的返回格式）
            formatted_item = {
                "title": item.get("title") or item.get("name") or "无标题",
                "url": item.get("url") or item.get("link") or "",
                "snippet": item.get("snippet") or item.get("description") or item.get("content") or ""
            }

            # 验证URL
            if SearchUtils.is_valid_url(formatted_item["url"]):
                formatted.append(formatted_item)

        return formatted

    @staticmethod
    def merge_scraped_content(scraped_results: List[Dict]) -> str:
        """
        合并多个爬取结果的文本内容

        Args:
            scraped_results: 爬取结果列表

        Returns:
            合并后的文本
        """
        merged_parts = []

        for idx, result in enumerate(scraped_results, 1):
            if not result.get("success"):
                continue

            url = result.get("url", "")
            content = result.get("content", {})
            text = content.get("text", "")

            if text and text.strip():
                # 添加来源标识
                merged_parts.append(f"=== 来源 {idx}: {url} ===\n\n{text}\n")

        return "\n\n".join(merged_parts)

    @staticmethod
    def extract_key_info_from_html(html: str, max_length: int = 10000) -> str:
        """
        从HTML中提取关键文本（去除标签、脚本、样式等）

        Args:
            html: HTML内容
            max_length: 最大保留长度

        Returns:
            提取的文本
        """
        if not html:
            return ""

        # 简单的HTML清理（实际项目中应使用 BeautifulSoup 等库）
        # 去除 script 和 style 标签
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # 去除所有HTML标签
        text = re.sub(r'<[^>]+>', '', text)

        # 去除多余空白
        text = re.sub(r'\s+', ' ', text)

        # 截断
        if len(text) > max_length:
            text = text[:max_length] + "..."

        return text.strip()

    # ========== Use Case 检测 ==========

    @staticmethod
    def auto_detect_use_case(query: str, target_urls: Optional[List[str]] = None) -> tuple[str, str]:
        """
        自动检测使用场景

        Args:
            query: 用户查询
            target_urls: 用户提供的URL列表（可选）

        Returns:
            (use_case, reason)
        """
        # 场景1: 用户明确提供了URL
        if target_urls and len(target_urls) > 0:
            return "url_analysis", f"用户提供了 {len(target_urls)} 个URL"

        # 场景2: 查询中包含URL
        urls_in_query = SearchUtils.extract_urls_from_text(query)
        if urls_in_query:
            return "url_analysis", f"查询中包含 {len(urls_in_query)} 个URL"

        # 场景3: 查询中包含"这个网页"、"这篇文章"等指示词
        analysis_keywords = ["这个网页", "这篇文章", "该页面", "此链接", "分析网页", "网页内容"]
        if any(keyword in query for keyword in analysis_keywords):
            return "url_analysis", "查询包含URL分析相关的指示词"

        # 默认：搜索引擎检索
        return "search", "未检测到URL，默认使用搜索引擎检索"

    # ========== 状态验证 ==========

    def validate_state(self, state: Dict) -> None:
        """
        验证状态是否包含必需字段

        Args:
            state: SearchState

        Raises:
            ValueError: 如果缺少必需字段
        """
        required_fields = ["query"]

        for field in required_fields:
            if field not in state or not state[field]:
                raise ValueError(f"SearchState 缺少必需字段: {field}")

        logger.debug(f"✅ [Utils] State 验证通过")

    # ========== 搜索缓存管理 ==========

    @staticmethod
    def generate_query_hash(query: str) -> str:
        """
        生成查询的哈希值（用于缓存文件名）

        Args:
            query: 查询字符串

        Returns:
            MD5 哈希值
        """
        import hashlib
        return hashlib.md5(query.strip().lower().encode('utf-8')).hexdigest()

    @staticmethod
    def save_search_cache(
        query: str,
        sources: List[Dict],
        answer: Optional[str] = None
    ) -> str:
        """
        保存搜索结果到缓存

        Args:
            query: 原始查询
            sources: 来源列表 [{"url": str, "title": str, "content": Dict}, ...]
            answer: 生成的答案（可选）

        Returns:
            缓存文件路径
        """
        import json
        from datetime import datetime
        from pathlib import Path
        from src.config.constants import PathConstants

        # 生成查询哈希
        query_hash = SearchUtils.generate_query_hash(query)

        # 缓存目录
        cache_dir = Path(PathConstants.DATA_ROOT) / PathConstants.SEARCH_CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)

        # 缓存文件路径
        cache_file = cache_dir / f"{query_hash}.json"

        # 构建缓存数据
        cache_data = {
            "query": query,
            "query_hash": query_hash,
            "timestamp": datetime.now().isoformat(),
            "sources": sources,
            "answer": answer
        }

        # 保存到文件
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)

        logger.info(f"💾 [Cache] 搜索结果已保存: {cache_file}")
        logger.info(f"   - 查询: {query[:50]}...")
        logger.info(f"   - 来源数量: {len(sources)}")

        return str(cache_file)

    @staticmethod
    def load_search_cache(query: str) -> Optional[Dict]:
        """
        加载搜索缓存

        Args:
            query: 查询字符串

        Returns:
            缓存数据，如果不存在返回 None
        """
        import json
        from pathlib import Path
        from src.config.constants import PathConstants

        # 生成查询哈希
        query_hash = SearchUtils.generate_query_hash(query)

        # 缓存文件路径
        cache_dir = Path(PathConstants.DATA_ROOT) / PathConstants.SEARCH_CACHE_DIR
        cache_file = cache_dir / f"{query_hash}.json"

        # 检查文件是否存在
        if not cache_file.exists():
            return None

        # 读取缓存
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            logger.info(f"📦 [Cache] 找到缓存: {cache_file}")
            logger.info(f"   - 查询: {cache_data['query'][:50]}...")
            logger.info(f"   - 时间: {cache_data['timestamp']}")
            logger.info(f"   - 来源数量: {len(cache_data['sources'])}")

            return cache_data

        except Exception as e:
            logger.warning(f"⚠️  [Cache] 读取缓存失败: {e}")
            return None

    @staticmethod
    def has_search_cache(query: str) -> bool:
        """
        检查是否有缓存

        Args:
            query: 查询字符串

        Returns:
            是否存在缓存
        """
        from pathlib import Path
        from src.config.constants import PathConstants

        query_hash = SearchUtils.generate_query_hash(query)
        cache_dir = Path(PathConstants.DATA_ROOT) / PathConstants.SEARCH_CACHE_DIR
        cache_file = cache_dir / f"{query_hash}.json"

        return cache_file.exists()

    # ========== Use Case 2: Web 内容保存 ==========

    @staticmethod
    def save_web_content(url: str, content: Dict, metadata: Optional[Dict] = None) -> str:
        """
        保存 URL 内容到 JSON 文件（Use Case 2）

        Args:
            url: URL 地址
            content: 内容数据 {"text": str, "html": str, "json": Dict}
            metadata: 元数据（可选）

        Returns:
            保存的文件路径
        """
        import json
        from datetime import datetime
        from pathlib import Path
        from src.config.constants import PathConstants

        # 生成 URL 哈希作为文件名
        url_hash = SearchUtils.generate_query_hash(url)

        # 目录
        web_dir = Path(PathConstants.DATA_ROOT) / PathConstants.WEB_CONTENT_DIR
        web_dir.mkdir(parents=True, exist_ok=True)

        # 文件路径
        json_file = web_dir / f"{url_hash}.json"

        # 构建数据
        data = {
            "url": url,
            "url_hash": url_hash,
            "timestamp": datetime.now().isoformat(),
            "content": content,
            "metadata": metadata or {}
        }

        # 保存
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"💾 [WebContent] URL 内容已保存: {json_file}")
        logger.info(f"   - URL: {url}")
        logger.info(f"   - 文本长度: {len(content.get('text', ''))} 字符")

        return str(json_file)

    @staticmethod
    def load_web_content(url: str) -> Optional[Dict]:
        """
        加载已保存的 URL 内容

        Args:
            url: URL 地址

        Returns:
            内容数据，如果不存在返回 None
        """
        import json
        from pathlib import Path
        from src.config.constants import PathConstants

        url_hash = SearchUtils.generate_query_hash(url)
        web_dir = Path(PathConstants.DATA_ROOT) / PathConstants.WEB_CONTENT_DIR
        json_file = web_dir / f"{url_hash}.json"

        if not json_file.exists():
            return None

        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            logger.info(f"📦 [WebContent] 找到已保存内容: {json_file}")
            return data

        except Exception as e:
            logger.warning(f"⚠️  [WebContent] 读取内容失败: {e}")
            return None

    @staticmethod
    def generate_doc_name_from_url(url: str) -> str:
        """
        从 URL 生成文档名（用于 IndexingAgent）

        Args:
            url: URL 地址

        Returns:
            文档名称，格式：web_{domain}_{hash[:8]}
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        domain = parsed.netloc.replace('.', '_').replace(':', '_')
        url_hash = SearchUtils.generate_query_hash(url)[:8]

        return f"web_{domain}_{url_hash}"
