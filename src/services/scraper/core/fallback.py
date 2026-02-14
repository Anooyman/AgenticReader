# scraper/core/fallback.py
"""降级处理器

本模块提供降级处理机制，当 Playwright 浏览器自动化失败时自动切换到更简单的 HTTP 客户端：
- Playwright 失败时降级到 httpx
- 智能判断是否应该降级（根据错误类型）
- 保持统一的返回格式
- 适用于简单页面或浏览器不可用的场景

适用场景：
- Playwright 浏览器启动失败（系统资源不足、浏览器未安装）
- 超时错误（页面加载过慢）
- 连接错误（网络问题）
- 不需要 JavaScript 渲染的静态页面

不适用场景：
- 需要 JavaScript 渲染的动态页面（SPA、React/Vue 应用）
- 需要模拟用户交互的场景（点击、滚动等）
- 需要反爬虫检测的场景（Cloudflare、验证码等）

使用示例：
    >>> from scraper.core.fallback import FallbackHandler
    >>> from scraper.config.scraper_config import ScraperConfig
    >>>
    >>> # 创建降级处理器
    >>> config = ScraperConfig()
    >>> fallback = FallbackHandler(config)
    >>>
    >>> # 尝试 Playwright，失败时自动降级
    >>> try:
    ...     # 尝试使用 Playwright
    ...     result = await scrape_with_playwright(url)
    ... except Exception as e:
    ...     # 检查是否应该降级
    ...     if fallback.should_fallback(e):
    ...         # 降级到 httpx
    ...         result = await fallback.fetch_with_httpx(url)
    ...     else:
    ...         # 不适合降级，重新抛出异常
    ...         raise
"""
import httpx
from typing import Dict, Optional
from scraper.config.scraper_config import ScraperConfig


class FallbackHandler:
    """降级处理器类

    当浏览器自动化（Playwright）失败时，提供降级到简单 HTTP 客户端（httpx）的功能。

    主要功能：
    - 使用 httpx 作为后备方案获取 HTML 内容
    - 智能判断哪些错误适合降级（浏览器故障、超时等）
    - 保持与 Playwright 一致的返回格式
    - 自动处理重定向和常见 HTTP 问题

    降级策略：
    1. Playwright 执行失败
    2. 检查错误类型（使用 should_fallback 方法）
    3. 如果适合降级，使用 httpx 重新尝试
    4. 返回统一格式的结果

    优点：
    - 提高成功率：浏览器失败时仍能获取内容
    - 更轻量：httpx 比 Playwright 占用资源少
    - 更快速：简单页面用 httpx 更快

    缺点：
    - 无法执行 JavaScript（只能获取原始 HTML）
    - 无法模拟用户交互（点击、滚动等）
    - 反爬虫能力较弱（容易被识别）

    属性：
        config (ScraperConfig): 配置实例，包含超时、User-Agent 等设置

    示例：
        >>> # 创建降级处理器
        >>> config = ScraperConfig(timeout=30000)
        >>> fallback = FallbackHandler(config)
        >>>
        >>> # 在 Playwright 失败时使用
        >>> try:
        ...     content = await playwright_scrape(url)
        ... except Exception as e:
        ...     if fallback.should_fallback(e):
        ...         print("Playwright 失败，降级到 httpx")
        ...         content = await fallback.fetch_with_httpx(url)
        ...     else:
        ...         raise  # 不适合降级，重新抛出
    """

    def __init__(self, config: ScraperConfig):
        """初始化降级处理器

        参数：
            config: ScraperConfig 配置实例，包含：
                - timeout: 请求超时时间（毫秒）
                - user_agent: 自定义 User-Agent（可选）

        示例：
            >>> from pathlib import Path
            >>> config = ScraperConfig(
            ...     timeout=30000,
            ...     user_agent="Mozilla/5.0 (Fallback Client)"
            ... )
            >>> fallback = FallbackHandler(config)
        """
        self.config = config

    async def fetch_with_httpx(self, url: str) -> Dict[str, any]:
        """使用 httpx 作为降级方案获取 URL 内容

        当 Playwright 失败时，使用这个方法作为后备方案。
        直接发送 HTTP GET 请求获取页面的原始 HTML，不执行 JavaScript。

        功能特点：
        - 使用配置的 timeout 和 user_agent
        - 自动跟随重定向（最多 10 次）
        - 自动处理 gzip/deflate 压缩
        - 返回与 Playwright 一致的数据格式

        适用场景：
        - 静态 HTML 页面（不需要 JavaScript）
        - API 端点（JSON 数据）
        - 简单的网页内容

        不适用场景：
        - 单页应用（SPA）需要 JavaScript 渲染
        - 动态加载的内容（AJAX）
        - 需要模拟用户交互的页面

        参数：
            url: 目标 URL（完整的 HTTP/HTTPS 地址）

        返回：
            Dict[str, any]: 包含以下字段的字典：
                - html (str): 页面的 HTML 内容
                - status_code (int): HTTP 状态码（如 200, 404, 500）
                - headers (dict): 响应头部信息
                - url (str): 最终 URL（可能与请求 URL 不同，如果有重定向）
                - method (str): 固定值 "httpx_fallback"，标识使用了降级方案

        异常：
            httpx.HTTPStatusError: HTTP 错误（4xx, 5xx）
            httpx.TimeoutException: 请求超时
            httpx.RequestError: 网络错误

        示例 1 - 基本用法：
            >>> fallback = FallbackHandler(config)
            >>> result = await fallback.fetch_with_httpx("https://example.com")
            >>> print(f"状态码: {result['status_code']}")
            状态码: 200
            >>> print(f"HTML 长度: {len(result['html'])} 字符")
            HTML 长度: 1256 字符
            >>> print(f"使用方法: {result['method']}")
            使用方法: httpx_fallback

        示例 2 - 处理重定向：
            >>> # 访问一个会重定向的 URL
            >>> result = await fallback.fetch_with_httpx("http://example.com")
            >>> # 自动跟随重定向到 https://example.com
            >>> print(f"最终 URL: {result['url']}")
            最终 URL: https://example.com/
            >>> print(f"重定向次数可从 headers 中推断")

        示例 3 - 获取 JSON API：
            >>> # httpx 也可以用于 API 端点
            >>> result = await fallback.fetch_with_httpx("https://api.example.com/data")
            >>> import json
            >>> data = json.loads(result['html'])  # 'html' 字段包含 JSON 字符串
            >>> print(data)

        示例 4 - 在实际降级场景中使用：
            >>> from scraper.core.browser import BrowserManager
            >>>
            >>> try:
            ...     # 尝试使用 Playwright
            ...     browser_manager = BrowserManager()
            ...     await browser_manager.launch_browser(config)
            ...     # ... 执行爬取
            ... except Exception as e:
            ...     # Playwright 失败
            ...     if fallback.should_fallback(e):
            ...         print(f"Playwright 失败: {e}")
            ...         print("降级到 httpx 重新尝试...")
            ...         result = await fallback.fetch_with_httpx(url)
            ...         html = result['html']
        """
        # 创建异步 HTTP 客户端
        async with httpx.AsyncClient(
            # 超时设置（从配置的毫秒转换为秒）
            timeout=self.config.timeout / 1000,

            # 请求头：使用配置的 User-Agent（如果有）
            headers={"User-Agent": self.config.user_agent},

            # 自动跟随重定向（如 301、302、303、307、308）
            follow_redirects=True
        ) as client:
            # 发送 GET 请求
            response = await client.get(url)

            # 检查 HTTP 状态码，如果是错误码（4xx、5xx）则抛出异常
            # 例如：404 Not Found、500 Internal Server Error
            response.raise_for_status()

            # 返回统一格式的结果
            return {
                # HTML 内容（字符串形式）
                "html": response.text,

                # HTTP 状态码（200 表示成功）
                "status_code": response.status_code,

                # 响应头部（转换为普通字典）
                # 例如：{"content-type": "text/html", "content-length": "1234"}
                "headers": dict(response.headers),

                # 最终 URL（考虑重定向后的 URL）
                "url": str(response.url),

                # 标识使用了降级方案（区分于 Playwright）
                "method": "httpx_fallback"
            }

    def should_fallback(self, error: Exception) -> bool:
        """判断是否应该降级到更简单的方法

        分析异常信息，决定是否适合使用 httpx 降级。
        主要检查错误消息中的关键词来判断错误类型。

        适合降级的错误：
        - 浏览器启动失败（browser launch failed）
        - 浏览器连接超时（browser timeout）
        - Chromium 不可用（chromium not found）
        - 页面加载超时（page timeout）
        - 网络连接错误（connection error）

        不适合降级的错误：
        - 反爬虫检测（需要真实浏览器）
        - 内容未找到（降级也找不到）
        - 配置错误（需要修复配置）

        参数：
            error: 发生的异常对象

        返回：
            bool: True 表示应该降级，False 表示不应该降级

        示例 1 - 浏览器启动失败：
            >>> try:
            ...     await browser.launch()
            ... except Exception as e:
            ...     # e 的消息可能是 "Browser launch failed"
            ...     if fallback.should_fallback(e):
            ...         print("浏览器启动失败，降级到 httpx")
            ...         result = await fallback.fetch_with_httpx(url)

        示例 2 - 超时错误：
            >>> try:
            ...     await page.goto(url, timeout=5000)
            ... except Exception as e:
            ...     # e 的消息可能是 "Timeout 5000ms exceeded"
            ...     if fallback.should_fallback(e):
            ...         print("页面加载超时，尝试 httpx")
            ...         result = await fallback.fetch_with_httpx(url)

        示例 3 - 不应该降级的情况：
            >>> from scraper.exceptions import AntiBotDetection
            >>>
            >>> try:
            ...     await scrape_protected_site(url)
            ... except AntiBotDetection as e:
            ...     # 反爬虫检测错误，不应该降级
            ...     # 因为 httpx 更容易被检测
            ...     if fallback.should_fallback(e):
            ...         # 通常返回 False
            ...         pass
            ...     else:
            ...         print("遇到反爬虫，需要增强策略")
            ...         # 应该使用更强的反检测技术

        示例 4 - 实际使用模式：
            >>> async def scrape_with_auto_fallback(url: str):
            ...     try:
            ...         # 首先尝试 Playwright（功能最强）
            ...         return await scrape_with_playwright(url)
            ...     except Exception as e:
            ...         # 检查是否适合降级
            ...         if fallback.should_fallback(e):
            ...             print(f"Playwright 失败: {e}")
            ...             print("自动降级到 httpx...")
            ...             # 降级到 httpx（轻量级）
            ...             return await fallback.fetch_with_httpx(url)
            ...         else:
            ...             # 不适合降级，重新抛出异常
            ...             print(f"不可恢复的错误: {e}")
            ...             raise
        """
        # 将异常消息转换为小写，方便匹配
        error_msg = str(error).lower()

        # 定义适合降级的错误关键词
        fallback_indicators = [
            "timeout",      # 超时错误（页面加载超时、请求超时等）
            "browser",      # 浏览器相关错误（启动失败、崩溃等）
            "launch",       # 启动失败（浏览器进程无法启动）
            "chromium",     # Chromium 相关错误（未安装、版本不兼容等）
            "connection",   # 连接错误（网络问题、连接被拒绝等）
        ]

        # 检查错误消息中是否包含任何一个关键词
        # 只要包含一个，就认为适合降级
        return any(indicator in error_msg for indicator in fallback_indicators)
