# scraper/core/downloader.py
"""资源下载器

本模块提供网页资源下载功能，支持下载图片、PDF、视频等多种文件类型：
- 图片批量下载（支持 JPG, PNG, GIF, WebP 等格式）
- CSS 选择器过滤
- 数量限制
- Data URL 和 HTTP URL 支持
- 自动文件类型检测

使用示例：
    >>> from scraper.core.downloader import ResourceDownloader
    >>> from scraper.config.scraper_config import ScraperConfig
    >>>
    >>> # 创建下载器实例
    >>> config = ScraperConfig()
    >>> downloader = ResourceDownloader(config)
    >>>
    >>> # 下载页面中的所有图片
    >>> downloaded_files = await downloader.download_images(
    ...     page=page,
    ...     url="https://example.com",
    ...     max_count=10
    ... )
    >>> print(f"下载了 {len(downloaded_files)} 张图片")
    >>>
    >>> # 使用选择器只下载特定图片
    >>> gallery_images = await downloader.download_images(
    ...     page=page,
    ...     url="https://gallery.com",
    ...     selector=".gallery-image",  # 只下载 class="gallery-image" 的图片
    ...     max_count=5
    ... )
"""
from typing import List, Optional
from pathlib import Path
from playwright.async_api import Page
from scraper.config.scraper_config import ScraperConfig
import httpx
import base64
from scraper.storage.file_manager import FileManager


class ResourceDownloader:
    """资源下载器类

    负责从网页下载各种资源文件，包括图片、PDF、视频等。
    支持两种下载方式：
    1. 从页面中提取并下载图片（download_images）
    2. 从 URL 列表直接下载（download_by_urls）

    主要功能：
    - 智能处理 Data URL（base64 编码）和 HTTP URL
    - 支持 CSS 选择器过滤目标资源
    - 自动检测文件类型（从 content-type 或 data URL）
    - 自动保存到分类目录（images/pdfs/videos）
    - 错误容错：单个文件下载失败不影响其他文件

    属性：
        config (ScraperConfig): 配置实例，包含保存路径等设置

    示例：
        >>> # 创建下载器
        >>> config = ScraperConfig(base_dir=Path("./downloads"))
        >>> downloader = ResourceDownloader(config)
        >>>
        >>> # 下载网页图片
        >>> paths = await downloader.download_images(
        ...     page=page,
        ...     url="https://example.com",
        ...     selector="img.product-image",  # 只下载产品图片
        ...     max_count=20
        ... )
        >>> print(f"成功下载: {len(paths)} 张图片")
        成功下载: 15 张图片
    """

    def __init__(self, config: ScraperConfig):
        """初始化资源下载器

        参数：
            config: ScraperConfig 配置实例，包含：
                - base_dir: 文件保存的根目录
                - timeout: 下载超时时间（毫秒）

        示例：
            >>> from pathlib import Path
            >>> config = ScraperConfig(
            ...     base_dir=Path("./my_downloads"),
            ...     timeout=30000
            ... )
            >>> downloader = ResourceDownloader(config)
        """
        self.config = config

    async def download_images(
        self,
        page: Page,
        url: str,
        selector: Optional[str] = None,
        max_count: int = 50
    ) -> List[Path]:
        """从网页下载图片

        提取页面中的所有图片元素，并批量下载到本地。
        支持：
        - Data URLs（base64 编码的内嵌图片）
        - HTTP/HTTPS URLs（外部图片链接）
        - CSS 选择器过滤（只下载特定元素的图片）
        - 数量限制（避免下载过多）

        下载流程：
        1. 使用 JavaScript 在页面中提取所有图片的 src 属性
        2. 根据 selector 过滤（如果指定）
        3. 限制数量到 max_count
        4. 逐个下载并保存到 images/ 目录
        5. 返回所有成功下载的文件路径

        参数：
            page: Playwright 页面对象
            url: 源网页 URL，用于文件命名
            selector: 可选的 CSS 选择器，用于过滤图片
                - None: 下载所有 <img> 标签的图片
                - ".gallery": 只下载 class="gallery" 的图片
                - "img.product": 只下载 class="product" 的 <img> 标签
            max_count: 最大下载数量，默认 50 张
                - 防止下载过多图片占用空间
                - 常用值：10-100

        返回：
            List[Path]: 成功下载的图片文件路径列表
                例如：[Path("scraped_data/images/example.com_1.jpg"),
                       Path("scraped_data/images/example.com_2.png")]

        异常：
            - 单个图片下载失败会被忽略，不影响其他图片
            - 如果全部失败，返回空列表 []

        示例 1 - 下载所有图片：
            >>> # 下载页面中的所有图片
            >>> await page.goto("https://example.com")
            >>> images = await downloader.download_images(
            ...     page=page,
            ...     url="https://example.com",
            ...     max_count=10
            ... )
            >>> print(f"下载了 {len(images)} 张图片")
            下载了 10 张图片

        示例 2 - 使用选择器过滤：
            >>> # 只下载产品图片
            >>> images = await downloader.download_images(
            ...     page=page,
            ...     url="https://shop.com/product/123",
            ...     selector="img.product-image",  # 只下载产品图片
            ...     max_count=5
            ... )
            >>> for img_path in images:
            ...     print(f"- {img_path.name}")
            - shop.com_1.jpg
            - shop.com_2.jpg

        示例 3 - 下载画廊图片：
            >>> # 下载画廊中的大图
            >>> gallery_images = await downloader.download_images(
            ...     page=page,
            ...     url="https://gallery.com",
            ...     selector=".gallery-item img",  # 画廊项中的图片
            ...     max_count=20
            ... )
            >>> total_size = sum(img.stat().st_size for img in gallery_images)
            >>> print(f"总大小: {total_size / 1024 / 1024:.2f} MB")
            总大小: 15.34 MB
        """
        # 初始化文件管理器，用于保存图片
        file_manager = FileManager(self.config)
        file_manager.setup_directories()

        # 第一步：提取所有图片的 src 属性
        # 如果指定了 selector，使用它；否则使用默认的 "img"
        img_selector = selector if selector else "img"

        # 在浏览器中执行 JavaScript 代码来提取图片 URL
        img_sources = await page.evaluate(f"""
        () => {{
            // 查找所有匹配选择器的图片元素
            const images = document.querySelectorAll('{img_selector}');

            // 提取每个图片的 src 属性，过滤掉空值
            return Array.from(images).map(img => img.src).filter(src => src);
        }}
        """)

        # 第二步：限制下载数量
        # 只取前 max_count 个图片 URL
        img_sources = img_sources[:max_count]

        # 存储成功下载的文件路径
        downloaded_paths = []

        # 第三步：逐个下载图片
        for img_src in img_sources:
            try:
                # 处理 Data URL（base64 编码的内嵌图片）
                # 格式：data:image/png;base64,iVBORw0KGgoAAAANSUhEUgA...
                if img_src.startswith('data:image/'):
                    # 分割 Data URL：["data:image/png;base64", "iVBORw0KGgo..."]
                    parts = img_src.split(',', 1)
                    if len(parts) == 2:
                        # 解码 base64 数据为二进制
                        img_data = base64.b64decode(parts[1])

                        # 保存图片文件
                        path = file_manager.save_image(url, img_data)
                        downloaded_paths.append(path)

                # 处理 HTTP/HTTPS URL（外部图片链接）
                elif img_src.startswith('http'):
                    # 使用 httpx 异步下载图片
                    async with httpx.AsyncClient() as client:
                        # 发送 GET 请求下载图片，超时 30 秒
                        response = await client.get(img_src, timeout=30)

                        # 只有成功响应（200 OK）才保存
                        if response.status_code == 200:
                            # 保存图片的二进制内容
                            path = file_manager.save_image(url, response.content)
                            downloaded_paths.append(path)

            except Exception:
                # 单个图片下载失败，跳过继续下载其他图片
                # 这样可以确保一个失败不影响整体
                continue

        # 返回所有成功下载的文件路径
        return downloaded_paths

    async def download_by_urls(
        self, urls: List[str], source_url: str
    ) -> List[Path]:
        """从 URL 列表直接下载文件

        不需要浏览器页面，直接从给定的 URL 列表下载文件。
        适用于已经获取了资源 URL 列表的场景。

        支持的 URL 类型：
        - Data URLs: data:image/png;base64,iVBORw0KG...
        - HTTP/HTTPS URLs: https://example.com/image.jpg

        自动检测文件类型：
        - Data URL: 从 MIME 类型检测（如 data:image/png）
        - HTTP URL: 从响应的 Content-Type 头部检测

        参数：
            urls: 要下载的 URL 列表
                例如：["https://example.com/1.jpg",
                       "https://example.com/2.png"]
            source_url: 源页面 URL，用于文件命名
                例如："https://example.com"

        返回：
            List[Path]: 成功下载的文件路径列表

        异常：
            - 单个 URL 下载失败会被忽略
            - 如果全部失败，返回空列表 []

        示例 1 - 下载图片列表：
            >>> # 已知的图片 URL 列表
            >>> image_urls = [
            ...     "https://example.com/photo1.jpg",
            ...     "https://example.com/photo2.png",
            ...     "https://example.com/photo3.jpg"
            ... ]
            >>>
            >>> # 批量下载
            >>> files = await downloader.download_by_urls(
            ...     urls=image_urls,
            ...     source_url="https://example.com"
            ... )
            >>> print(f"成功下载: {len(files)} 个文件")
            成功下载: 3 个文件

        示例 2 - 下载 Data URLs：
            >>> # Data URL 格式的图片（base64 编码）
            >>> data_urls = [
            ...     "data:image/png;base64,iVBORw0KGgo...",
            ...     "data:image/jpeg;base64,/9j/4AAQSkZ..."
            ... ]
            >>>
            >>> files = await downloader.download_by_urls(
            ...     urls=data_urls,
            ...     source_url="https://example.com"
            ... )

        示例 3 - 混合 URL 类型：
            >>> # 混合 HTTP URL 和 Data URL
            >>> mixed_urls = [
            ...     "https://cdn.example.com/image.jpg",
            ...     "data:image/png;base64,iVBORw0KGgo...",
            ...     "https://example.com/photo.png"
            ... ]
            >>>
            >>> files = await downloader.download_by_urls(
            ...     urls=mixed_urls,
            ...     source_url="https://example.com"
            ... )
            >>> for file in files:
            ...     size_kb = file.stat().st_size / 1024
            ...     print(f"{file.name}: {size_kb:.2f} KB")
        """
        # 初始化文件管理器
        file_manager = FileManager(self.config)
        file_manager.setup_directories()

        # 存储成功下载的文件路径
        downloaded_paths = []

        # 逐个处理 URL
        for url in urls:
            try:
                # 处理 Data URL（base64 编码的内嵌数据）
                if url.startswith('data:'):
                    # 分割 Data URL：["data:image/png;base64", "编码数据"]
                    parts = url.split(',', 1)
                    if len(parts) == 2:
                        # 解码 base64 数据为二进制
                        file_data = base64.b64decode(parts[1])

                        # 检测文件类型（从 Data URL 的 MIME 类型）
                        # 如果是图片类型（image/png, image/jpeg 等）
                        if 'image/' in parts[0]:
                            # 保存为图片文件
                            path = file_manager.save_image(source_url, file_data)
                            downloaded_paths.append(path)

                        # 未来可以添加更多文件类型：
                        # elif 'application/pdf' in parts[0]:
                        #     path = file_manager.save_pdf(source_url, file_data)

                # 处理 HTTP/HTTPS URL（外部资源链接）
                elif url.startswith('http'):
                    # 使用 httpx 异步下载
                    async with httpx.AsyncClient() as client:
                        # 发送 GET 请求，超时 30 秒
                        response = await client.get(url, timeout=30)

                        # 只处理成功响应（200 OK）
                        if response.status_code == 200:
                            # 从响应头获取内容类型
                            # 例如：'image/jpeg', 'image/png', 'application/pdf'
                            content_type = response.headers.get('content-type', '')

                            # 根据内容类型保存文件
                            if 'image/' in content_type:
                                # 图片类型
                                path = file_manager.save_image(source_url, response.content)
                                downloaded_paths.append(path)

                            # 未来可以添加更多文件类型：
                            # elif 'application/pdf' in content_type:
                            #     path = file_manager.save_pdf(source_url, response.content)
                            # elif 'video/' in content_type:
                            #     path = file_manager.save_video(source_url, response.content)

            except Exception:
                # 单个 URL 下载失败，跳过继续处理其他 URL
                # 常见错误：网络超时、无效 URL、编码错误等
                continue

        # 返回所有成功下载的文件路径
        return downloaded_paths
