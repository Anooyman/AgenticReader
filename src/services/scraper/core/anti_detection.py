# scraper/core/anti_detection.py
"""反爬虫检测引擎

本模块提供多种反检测策略，帮助爬虫规避网站的机器人检测：
- 真实的浏览器请求头生成
- 浏览器指纹随机化（视口、时区、语言等）
- 人类行为模拟（鼠标移动、随机滚动）

使用示例：
    >>> from scraper.core.anti_detection import AntiDetectionEngine
    >>>
    >>> # 创建反检测引擎实例
    >>> engine = AntiDetectionEngine()
    >>>
    >>> # 获取真实的 HTTP 头部
    >>> headers = engine.add_realistic_headers()
    >>> print(headers["User-Agent"])
    >>>
    >>> # 在页面上模拟人类行为
    >>> await engine.simulate_human_behavior(page)
"""
from typing import Optional, Dict, List
from playwright.async_api import BrowserContext, Page
import random
import asyncio


class AntiDetectionEngine:
    """反检测引擎类

    提供多种方法使自动化浏览器表现得更像真实用户，从而规避反爬虫检测。

    主要功能：
    1. 生成真实的浏览器请求头
    2. 随机化浏览器指纹（视口大小、设备信息等）
    3. 模拟人类浏览行为（鼠标移动、滚动等）

    属性：
        无特定属性，所有方法都是无状态的

    示例：
        >>> engine = AntiDetectionEngine()
        >>>
        >>> # 获取随机视口尺寸
        >>> viewport = engine._get_random_viewport()
        >>> print(f"宽度: {viewport['width']}, 高度: {viewport['height']}")
        >>>
        >>> # 应用到浏览器上下文
        >>> await engine.randomize_fingerprint(context)
    """

    def __init__(self):
        """初始化反检测引擎

        当前实现不需要任何初始化参数，所有方法都是独立的。
        """
        pass

    def add_realistic_headers(self) -> Dict[str, str]:
        """生成真实的 HTTP 请求头

        模拟真实浏览器的请求头，包括：
        - Accept: 接受的内容类型
        - Accept-Language: 语言偏好
        - Accept-Encoding: 支持的编码
        - sec-ch-ua: Chrome 的客户端提示头部
        - Sec-Fetch-*: 安全相关的请求头

        这些头部能让请求看起来像是来自真实的 Chrome 浏览器，
        而不是自动化工具。

        返回：
            Dict[str, str]: 包含真实请求头的字典

        示例：
            >>> engine = AntiDetectionEngine()
            >>> headers = engine.add_realistic_headers()
            >>> for key, value in headers.items():
            ...     print(f"{key}: {value}")
            Accept: text/html,application/xhtml+xml,...
            Accept-Language: en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7
            ...
        """
        return {
            # 接受 HTML、XML、图片等多种内容类型
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            # 语言偏好：英语（美国）、英语、中文（简体）、中文
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            # 支持的压缩编码
            "Accept-Encoding": "gzip, deflate, br",
            # Chrome 的品牌和版本信息（客户端提示）
            "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            # 不是移动设备
            "sec-ch-ua-mobile": "?0",
            # 运行平台
            "sec-ch-ua-platform": '"macOS"',
            # 安全相关：同站请求
            "Sec-Fetch-Site": "none",
            # 导航模式
            "Sec-Fetch-Mode": "navigate",
            # 用户触发的请求
            "Sec-Fetch-User": "?1",
            # 目标是文档（页面）
            "Sec-Fetch-Dest": "document",
        }

    def _get_random_viewport(self) -> Dict[str, int]:
        """获取随机的视口尺寸

        从常见的屏幕分辨率列表中随机选择一个，使每次访问
        使用不同的视口尺寸，避免被识别为自动化脚本。

        支持的分辨率包括：
        - 1920x1080 (Full HD)
        - 1366x768 (常见笔记本)
        - 1536x864 (Windows 默认缩放)
        - 1440x900 (MacBook)
        - 1280x720 (HD)

        返回：
            Dict[str, int]: 包含 width 和 height 的字典

        示例：
            >>> engine = AntiDetectionEngine()
            >>> for i in range(3):
            ...     viewport = engine._get_random_viewport()
            ...     print(f"第{i+1}次: {viewport['width']}x{viewport['height']}")
            第1次: 1920x1080
            第2次: 1366x768
            第3次: 1440x900
        """
        # 常见的屏幕分辨率列表
        common_viewports = [
            {"width": 1920, "height": 1080},  # Full HD，最常见的桌面分辨率
            {"width": 1366, "height": 768},   # 常见的笔记本分辨率
            {"width": 1536, "height": 864},   # Windows 125% 缩放的常见分辨率
            {"width": 1440, "height": 900},   # MacBook 常见分辨率
            {"width": 1280, "height": 720},   # HD 分辨率
        ]
        # 随机选择一个分辨率
        return random.choice(common_viewports)

    async def randomize_fingerprint(self, context: BrowserContext) -> None:
        """应用浏览器指纹随机化

        注意：Playwright 的浏览器上下文在创建后是不可变的，
        因此这个方法主要用于 API 兼容性。实际的指纹随机化
        应该在创建上下文时通过参数完成。

        真正的指纹随机化包括：
        - 随机化视口大小（通过 _get_random_viewport）
        - 随机化时区
        - 随机化语言设置
        - 等等

        参数：
            context: Playwright 浏览器上下文

        示例：
            >>> # 在 BrowserManager 中使用
            >>> engine = AntiDetectionEngine()
            >>> viewport = engine._get_random_viewport()
            >>> context = await browser.new_context(viewport=viewport)
            >>> await engine.randomize_fingerprint(context)  # API 兼容性调用
        """
        # Playwright 的上下文在创建后是不可变的
        # 指纹随机化应该在创建上下文时通过参数完成
        # 这个方法主要用于 API 兼容性，不执行实际操作
        pass

    async def simulate_human_behavior(self, page: Page) -> None:
        """在页面上模拟人类行为

        执行一系列随机的人类行为来避免被检测为机器人：

        1. 随机鼠标移动：
           - 移动 2-4 次到页面上的随机位置
           - 每次移动后短暂停顿（0.1-0.3秒）

        2. 随机滚动：
           - 向下滚动 200-800 像素
           - 滚动后停顿（0.2-0.5秒）

        这些行为能够触发网站的事件监听器，使浏览活动
        看起来更像真实用户。

        参数：
            page: Playwright 页面对象

        示例：
            >>> # 在访问页面后模拟人类行为
            >>> await page.goto("https://example.com")
            >>> engine = AntiDetectionEngine()
            >>> await engine.simulate_human_behavior(page)
            >>> # 然后再进行实际的爬取操作
            >>> content = await page.content()
        """
        # 第一步：随机鼠标移动
        # 移动次数：2-4 次（随机）
        move_count = random.randint(2, 4)
        for _ in range(move_count):
            # 生成随机的鼠标坐标
            # x: 100-500 像素（页面左侧区域）
            # y: 100-500 像素（页面上部区域）
            x = random.randint(100, 500)
            y = random.randint(100, 500)

            # 移动鼠标到该位置
            await page.mouse.move(x, y)

            # 随机停顿 0.1-0.3 秒，模拟人类思考时间
            await asyncio.sleep(random.uniform(0.1, 0.3))

        # 第二步：随机滚动页面
        # 滚动距离：200-800 像素（随机）
        scroll_distance = random.randint(200, 800)

        # 执行 JavaScript 滚动
        # window.scrollBy(0, distance) 表示向下滚动 distance 像素
        await page.evaluate(f"window.scrollBy(0, {scroll_distance})")

        # 滚动后停顿 0.2-0.5 秒
        await asyncio.sleep(random.uniform(0.2, 0.5))
