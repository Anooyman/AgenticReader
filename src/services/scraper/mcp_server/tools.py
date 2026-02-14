# scraper/mcp_server/tools.py
"""MCP 工具实现

本模块实现了 3 个核心 MCP 工具，供 AI 助手（如 Claude）通过 MCP 协议调用：

1. scrape_url_tool: 单页爬取工具
   - 爬取单个网页的 HTML、文本、JSON、截图
   - 支持等待动态内容加载
   - 自动保存到分类目录

2. scrape_batch_tool: 批量爬取工具
   - 批量爬取多个网页
   - 支持并发控制和速率限制
   - 返回详细的统计信息

3. download_resources_tool: 资源下载工具
   - 下载网页中的图片、PDF、视频等资源
   - 支持 CSS 选择器过滤
   - 支持数量限制

使用示例：
    >>> from scraper.mcp_server.tools import scrape_url_tool
    >>>
    >>> # 爬取单个网页
    >>> result = await scrape_url_tool(
    ...     url="https://example.com",
    ...     content_types=["html", "text", "screenshot"]
    ... )
    >>> print(f"成功: {result['success']}")
    >>> print(f"文件: {result['data']['files']}")
"""
from typing import List, Optional, Dict, Any
from pathlib import Path
from scraper.config.scraper_config import ScraperConfig
from scraper.core.browser import BrowserManager
from scraper.core.extractor import ContentExtractor
from scraper.core.downloader import ResourceDownloader
from scraper.storage.file_manager import FileManager
from scraper.storage.metadata import MetadataTracker, ScrapeMetadata
from datetime import datetime
import base64
import asyncio


async def scrape_url_tool(
    url: str,
    content_types: Optional[List[str]] = None,
    wait_for: Optional[str] = None,
    headless: bool = True,
    proxy: Optional[str] = None,
    user_agent: Optional[str] = None,
    timeout: int = 30000,
    base_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """爬取单个 URL 并返回内容

    这是最基础也是最强大的爬取工具，使用 Playwright 浏览器自动化来爬取网页内容。
    支持提取 HTML、文本、JSON、截图等多种内容类型，并自动保存到分类目录。

    功能特点：
    - 真实浏览器渲染（支持 JavaScript）
    - 多种内容类型提取（HTML/文本/JSON/截图）
    - 等待动态内容加载（CSS 选择器）
    - 自动反爬虫检测（随机指纹、真实头部）
    - 分类文件存储（html/json/images）
    - 完整的元数据记录（时间、耗时、状态码）

    参数：
        url: 目标网页的完整 URL
            例如：\"https://example.com\"
        content_types: 要提取的内容类型列表，默认 [\"html\", \"text\"]
            可选值：
            - \"html\": 完整的 HTML 源代码
            - \"text\": 纯文本内容（移除标签和脚本）
            - \"json\": JSON 数据（从 script 标签或 API 响应）
            - \"screenshot\": 网页截图（PNG 格式）
        wait_for: 可选的 CSS 选择器，等待该元素出现后再提取内容
            例如：\".content-loaded\" 或 \"#main-content\"
            适用于动态加载的 SPA 应用
        headless: 是否使用无头模式，默认 True
            - True: 后台运行，不显示浏览器窗口（推荐）
            - False: 显示浏览器窗口（用于调试）
        proxy: 可选的代理服务器地址
            例如：\"http://proxy.example.com:8080\"
        user_agent: 可选的自定义 User-Agent
            例如：\"Mozilla/5.0 (Custom Bot)\"
        timeout: 请求超时时间（毫秒），默认 30000（30秒）
            建议值：
            - 快速页面：10000-20000ms
            - 慢速页面：30000-60000ms
        base_dir: 文件保存的根目录，默认 \"./scraped_data\"
            例如：Path(\"./my_data\")

    返回：
        Dict[str, Any]: 包含以下字段的字典：
            - success (bool): 是否成功
            - data (dict): 爬取的数据
                - url (str): 源 URL
                - content (dict): 提取的内容
                    - html (str): HTML 内容（如果请求）
                    - text (str): 文本内容（如果请求）
                    - json (dict): JSON 数据（如果请求且找到）
                    - screenshot (str): Base64 编码的截图（如果请求）
                - files (list): 保存的文件路径列表
                - metadata (dict): 元数据
                    - timestamp (str): 爬取时间
                    - duration_ms (int): 耗时（毫秒）
                    - status_code (int): HTTP 状态码
            - error (str): 错误信息（仅在失败时）

    异常：
        不抛出异常，所有错误都通过返回值的 \"error\" 字段返回

    示例 1 - 基本爬取：
        >>> result = await scrape_url_tool(
        ...     url=\"https://example.com\",
        ...     content_types=[\"html\", \"text\"]
        ... )
        >>> if result[\"success\"]:
        ...     html = result[\"data\"][\"content\"][\"html\"]
        ...     text = result[\"data\"][\"content\"][\"text\"]
        ...     print(f\"HTML 长度: {len(html)}\")
        ...     print(f\"文本预览: {text[:100]}...\")

    示例 2 - 爬取并截图：
        >>> result = await scrape_url_tool(
        ...     url=\"https://example.com\",
        ...     content_types=[\"screenshot\"],
        ...     base_dir=Path(\"./screenshots\")
        ... )
        >>> if result[\"success\"]:
        ...     screenshot_file = result[\"data\"][\"files\"][0]
        ...     print(f\"截图已保存: {screenshot_file}\")

    示例 3 - 等待动态内容：
        >>> result = await scrape_url_tool(
        ...     url=\"https://spa-app.com\",
        ...     content_types=[\"text\"],
        ...     wait_for=\".content-loaded\",  # 等待内容加载完成
        ...     timeout=60000  # 60 秒超时
        ... )

    示例 4 - 完整配置：
        >>> result = await scrape_url_tool(
        ...     url=\"https://api.example.com/data\",
        ...     content_types=[\"json\", \"html\"],
        ...     headless=True,
        ...     user_agent=\"Mozilla/5.0 (Custom Scraper)\",
        ...     timeout=30000,
        ...     base_dir=Path(\"./api_data\")
        ... )
        >>> if result[\"success\"]:
        ...     json_data = result[\"data\"][\"content\"][\"json\"]
        ...     print(f\"提取的数据: {json_data}\")
    """
    # 设置默认的内容类型
    if content_types is None:
        content_types = ["html", "text"]

    # 创建配置对象
    # 只包含 ScraperConfig 支持的参数，避免 TypeError
    config_kwargs = {
        "base_dir": base_dir or Path("./scraped_data"),
        "headless": headless,
        "timeout": timeout
    }
    # 只在提供了 user_agent 时才添加
    if user_agent:
        config_kwargs["user_agent"] = user_agent

    config = ScraperConfig(**config_kwargs)

    # 初始化所有必需的组件
    browser_manager = BrowserManager()     # 浏览器管理器
    extractor = ContentExtractor()         # 内容提取器
    file_manager = FileManager(config)     # 文件管理器
    metadata_tracker = MetadataTracker(config)  # 元数据追踪器

    # 创建目录结构（html/, json/, images/ 等）
    file_manager.setup_directories()

    # 记录开始时间，用于计算耗时
    start_time = datetime.now()

    try:
        # 第一步：启动浏览器并导航到目标页面
        await browser_manager.launch_browser(config)
        context = await browser_manager.get_context(config)
        page = await context.new_page()

        # 访问目标 URL
        # wait_until=\"networkidle\" 表示等待网络空闲（没有请求）
        response = await page.goto(url, wait_until="networkidle", timeout=timeout)

        # 第二步：等待特定元素出现（如果指定了 wait_for）
        # 适用于动态加载的内容
        if wait_for:
            await page.wait_for_selector(wait_for, timeout=timeout)

        # 第三步：提取内容
        content = {}       # 存储提取的内容
        saved_files = []   # 存储保存的文件路径

        # 提取 HTML
        if "html" in content_types:
            html = await extractor.extract_html(page)
            content["html"] = html
            # 保存 HTML 到文件
            html_path = file_manager.save_html(url, html)
            saved_files.append(str(html_path))

        # 提取文本
        if "text" in content_types:
            text = await extractor.extract_text(page)
            content["text"] = text
            # 注意：文本不单独保存文件，只返回在 content 中

        # 提取 JSON
        if "json" in content_types:
            json_data = await extractor.extract_json(page)
            if json_data:
                content["json"] = json_data
                # 保存 JSON 到文件
                json_path = file_manager.save_json(url, json_data)
                saved_files.append(str(json_path))

        # 提取截图
        if "screenshot" in content_types:
            screenshot = await extractor.extract_screenshot(page)
            # 转换为 base64 字符串（方便传输）
            content["screenshot"] = base64.b64encode(screenshot).decode('utf-8')
            # 保存截图到文件
            img_path = file_manager.save_image(url, screenshot)
            saved_files.append(str(img_path))

        # 第四步：计算耗时
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # 第五步：记录元数据到日志
        metadata = ScrapeMetadata(
            url=url,
            timestamp=datetime.now(),
            status="success",
            html_path=Path(saved_files[0]) if saved_files else Path(""),
            json_path=Path(saved_files[1]) if len(saved_files) > 1 else Path("")
        )
        metadata_tracker.log_metadata(metadata)

        # 第六步：清理资源
        await page.close()
        await browser_manager.release_context(context)
        await browser_manager.close_all()

        # 返回成功结果
        return {
            "success": True,
            "data": {
                "url": url,
                "content": content,       # 提取的内容
                "files": saved_files,     # 保存的文件路径
                "metadata": {
                    "timestamp": start_time.isoformat(),
                    "duration_ms": duration_ms,
                    "status_code": response.status if response else None
                }
            }
        }

    except Exception as e:
        # 发生错误时清理资源
        await browser_manager.close_all()

        # 返回失败结果
        return {
            "success": False,
            "error": str(e),
            "data": {
                "url": url,
                "files": [],
                "metadata": {
                    "timestamp": start_time.isoformat(),
                    "duration_ms": int((datetime.now() - start_time).total_seconds() * 1000)
                }
            }
        }


async def scrape_batch_tool(
    urls: List[str],
    content_types: Optional[List[str]] = None,
    concurrent_limit: int = 3,
    delay_between: int = 2000,
    **kwargs
) -> Dict[str, Any]:
    """批量爬取多个 URL

    高效地批量爬取多个网页，支持并发控制和速率限制，避免被服务器封禁。

    功能特点：
    - 并发爬取（提高效率）
    - 并发数限制（避免过载）
    - 请求间延迟（礼貌爬取）
    - 详细统计信息（成功/失败数量）
    - 每个 URL 独立结果

    适用场景：
    - 爬取列表页的所有文章
    - 批量下载产品页面
    - 监控多个网站
    - 数据采集工作流

    参数：
        urls: 要爬取的 URL 列表
            例如：[\"https://site1.com\", \"https://site2.com\"]
        content_types: 要提取的内容类型，默认 [\"html\", \"text\"]
            同 scrape_url_tool 的 content_types
        concurrent_limit: 最大并发数，默认 3
            - 设置过高会被封 IP
            - 设置过低效率不高
            - 推荐值：2-5
        delay_between: 请求间延迟（毫秒），默认 2000（2秒）
            - 0: 无延迟（不推荐）
            - 2000-5000: 常规网站
            - 5000+: 严格的网站
        **kwargs: 其他参数传递给 scrape_url_tool
            支持：headless, proxy, user_agent, timeout, base_dir 等

    返回：
        Dict[str, Any]: 包含以下字段的字典：
            - success (bool): 批量操作是否成功（总是 True）
            - data (dict): 批量爬取数据
                - total (int): 总 URL 数量
                - succeeded (int): 成功数量
                - failed (int): 失败数量
                - results (list): 每个 URL 的结果
                    - url (str): URL
                    - success (bool): 是否成功
                    - files (list): 保存的文件
                    - metadata (dict): 元数据
                    - error (str): 错误信息（如果失败）

    示例 1 - 基本批量爬取：
        >>> urls = [
        ...     \"https://example.com/page1\",
        ...     \"https://example.com/page2\",
        ...     \"https://example.com/page3\"
        ... ]
        >>> result = await scrape_batch_tool(
        ...     urls=urls,
        ...     content_types=[\"text\"],
        ...     concurrent_limit=2,
        ...     delay_between=3000
        ... )
        >>> print(f\"总数: {result['data']['total']}\")
        >>> print(f\"成功: {result['data']['succeeded']}\")
        >>> print(f\"失败: {result['data']['failed']}\")

    示例 2 - 批量爬取并分析结果：
        >>> result = await scrape_batch_tool(
        ...     urls=product_urls,
        ...     content_types=[\"html\", \"screenshot\"],
        ...     concurrent_limit=3
        ... )
        >>> for item in result['data']['results']:
        ...     if item['success']:
        ...         print(f\"✅ {item['url']}: {len(item['files'])} 个文件\")
        ...     else:
        ...         print(f\"❌ {item['url']}: {item['error']}\")

    示例 3 - 高并发爬取（谨慎使用）：
        >>> # 适用于自己的服务器或 API
        >>> result = await scrape_batch_tool(
        ...     urls=api_endpoints,
        ...     content_types=[\"json\"],
        ...     concurrent_limit=10,  # 高并发
        ...     delay_between=0       # 无延迟
        ... )

    示例 4 - 礼貌爬取（推荐）：
        >>> # 适用于公共网站
        >>> result = await scrape_batch_tool(
        ...     urls=news_articles,
        ...     content_types=[\"html\", \"text\"],
        ...     concurrent_limit=2,    # 低并发
        ...     delay_between=5000,    # 5 秒延迟
        ...     headless=True,
        ...     base_dir=Path(\"./news\")
        ... )
    """
    # 初始化结果统计
    results = []     # 存储每个 URL 的结果
    succeeded = 0    # 成功计数
    failed = 0       # 失败计数

    # 创建信号量来控制并发数
    # 例如：concurrent_limit=3 表示最多同时爬取 3 个页面
    semaphore = asyncio.Semaphore(concurrent_limit)

    async def scrape_with_limit(url: str) -> Dict[str, Any]:
        """带并发限制的爬取函数

        使用信号量确保不超过 concurrent_limit 个并发请求。

        参数：
            url: 要爬取的 URL

        返回：
            包含爬取结果的字典
        """
        # 使用 nonlocal 访问外部变量
        nonlocal succeeded, failed

        # 获取信号量（如果已达到限制，会在这里等待）
        async with semaphore:
            try:
                # 调用单页爬取工具
                result = await scrape_url_tool(
                    url=url,
                    content_types=content_types,
                    **kwargs  # 传递所有额外参数
                )

                # 更新统计
                if result.get("success"):
                    succeeded += 1
                else:
                    failed += 1

                # 添加延迟（如果配置了）
                # 这是在爬取完成后延迟，避免请求过于频繁
                if delay_between > 0:
                    await asyncio.sleep(delay_between / 1000)

                # 返回完整的结果（包含content）
                return {
                    "url": url,
                    "success": result.get("success", False),
                    "content": result.get("data", {}).get("content", {}),  # ← 添加content字段
                    "files": result.get("data", {}).get("files", []),
                    "metadata": result.get("data", {}).get("metadata", {}),
                    "error": result.get("error")
                }

            except Exception as e:
                # 单个 URL 失败不影响其他
                failed += 1
                return {
                    "url": url,
                    "success": False,
                    "error": str(e)
                }

    # 创建所有爬取任务
    # 这里创建任务但不立即执行，而是由信号量控制执行
    tasks = [scrape_with_limit(url) for url in urls]

    # 并发执行所有任务
    # gather 会等待所有任务完成
    results = await asyncio.gather(*tasks)

    # 返回批量结果
    return {
        "success": True,  # 批量操作本身总是成功（即使单个失败）
        "data": {
            "total": len(urls),
            "succeeded": succeeded,
            "failed": failed,
            "results": results  # 每个 URL 的详细结果
        }
    }


async def download_resources_tool(
    url: str,
    resource_types: Optional[List[str]] = None,
    selector: Optional[str] = None,
    max_files: int = 50,
    base_dir: Optional[Path] = None,
    **kwargs
) -> Dict[str, Any]:
    """从 URL 下载资源文件

    专门用于下载网页中的资源文件（图片、PDF、视频等），而不是提取文本内容。

    功能特点：
    - 批量下载图片
    - CSS 选择器过滤
    - 数量限制（避免下载过多）
    - 自动文件类型检测
    - Data URL 和 HTTP URL 支持

    适用场景：
    - 下载图库照片
    - 下载产品图片
    - 下载文章配图
    - 批量下载媒体资源

    参数：
        url: 目标网页 URL
            例如：\"https://gallery.example.com\"
        resource_types: 要下载的资源类型，默认 [\"images\"]
            可选值：
            - \"images\": 图片（JPG, PNG, GIF, WebP）
            - \"pdfs\": PDF 文档（计划中）
            - \"videos\": 视频（计划中）
            - \"all\": 所有资源
        selector: 可选的 CSS 选择器，只下载匹配的资源
            例如：\".gallery-image\" 或 \"img.product\"
            - None: 下载所有 <img> 标签
            - \".gallery\": 只下载 class=\"gallery\" 的图片
        max_files: 最大下载数量，默认 50
            - 防止下载过多文件
            - 推荐值：10-100
        base_dir: 文件保存目录，默认 \"./scraped_data\"
            例如：Path(\"./downloads\")
        **kwargs: 其他浏览器配置参数
            支持：headless, proxy, user_agent, timeout

    返回：
        Dict[str, Any]: 包含以下字段的字典：
            - success (bool): 是否成功
            - data (dict): 下载数据
                - url (str): 源 URL
                - downloaded_files (list): 下载的文件路径列表
                - count (int): 下载的文件数量
                - metadata (dict): 元数据
                    - timestamp (str): 下载时间
                    - duration_ms (int): 耗时（毫秒）
            - error (str): 错误信息（仅在失败时）

    异常：
        不抛出异常，所有错误都通过返回值的 \"error\" 字段返回

    示例 1 - 下载所有图片：
        >>> result = await download_resources_tool(
        ...     url=\"https://unsplash.com\",
        ...     resource_types=[\"images\"],
        ...     max_files=10
        ... )
        >>> if result[\"success\"]:
        ...     files = result[\"data\"][\"downloaded_files\"]
        ...     print(f\"下载了 {len(files)} 张图片\")
        ...     for file in files:
        ...         print(f\"- {file}\")

    示例 2 - 使用选择器过滤：
        >>> result = await download_resources_tool(
        ...     url=\"https://shop.com/product/123\",
        ...     resource_types=[\"images\"],
        ...     selector=\".product-image\",  # 只下载产品图片
        ...     max_files=5,
        ...     base_dir=Path(\"./products\")
        ... )

    示例 3 - 下载画廊图片：
        >>> result = await download_resources_tool(
        ...     url=\"https://photo-gallery.com\",
        ...     resource_types=[\"images\"],
        ...     selector=\".gallery-item img\",  # 画廊项中的图片
        ...     max_files=20
        ... )
        >>> if result[\"success\"]:
        ...     count = result[\"data\"][\"count\"]
        ...     duration = result[\"data\"][\"metadata\"][\"duration_ms\"]
        ...     print(f\"下载 {count} 张图片，耗时 {duration}ms\")

    示例 4 - 完整配置：
        >>> result = await download_resources_tool(
        ...     url=\"https://example.com/images\",
        ...     resource_types=[\"images\"],
        ...     selector=None,  # 所有图片
        ...     max_files=100,
        ...     base_dir=Path(\"./image_archive\"),
        ...     headless=True,
        ...     timeout=60000
        ... )
    """
    # 设置默认的资源类型
    if resource_types is None:
        resource_types = ["images"]

    # 创建配置对象
    # 只提取 ScraperConfig 支持的参数
    config = ScraperConfig(
        base_dir=base_dir or Path("./scraped_data"),
        **{k: v for k, v in kwargs.items() if k in ['headless', 'proxy', 'user_agent', 'timeout']}
    )

    # 初始化组件
    browser_manager = BrowserManager()
    downloader = ResourceDownloader(config)

    # 记录开始时间
    start_time = datetime.now()
    downloaded_files = []  # 存储下载的文件路径

    try:
        # 第一步：启动浏览器并访问页面
        await browser_manager.launch_browser(config)
        context = await browser_manager.get_context(config)
        page = await context.new_page()

        # 访问目标 URL
        await page.goto(url, wait_until="networkidle")

        # 第二步：根据资源类型下载
        if "images" in resource_types or "all" in resource_types:
            # 下载图片
            image_paths = await downloader.download_images(
                page, url,
                selector=selector,    # CSS 选择器过滤
                max_count=max_files   # 最大数量限制
            )
            # 转换为字符串路径
            downloaded_files.extend([str(p) for p in image_paths])

        # 未来可以添加更多资源类型：
        # if "pdfs" in resource_types or "all" in resource_types:
        #     pdf_paths = await downloader.download_pdfs(page, url, max_count=max_files)
        #     downloaded_files.extend([str(p) for p in pdf_paths])

        # 第三步：清理资源
        await page.close()
        await browser_manager.release_context(context)
        await browser_manager.close_all()

        # 计算耗时
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # 返回成功结果
        return {
            "success": True,
            "data": {
                "url": url,
                "downloaded_files": downloaded_files,  # 文件路径列表
                "count": len(downloaded_files),        # 文件数量
                "metadata": {
                    "timestamp": start_time.isoformat(),
                    "duration_ms": duration_ms
                }
            }
        }

    except Exception as e:
        # 发生错误时清理资源
        await browser_manager.close_all()

        # 返回失败结果
        return {
            "success": False,
            "error": str(e),
            "data": {
                "url": url,
                "downloaded_files": [],
                "count": 0
            }
        }
