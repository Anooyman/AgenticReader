# scraper/core/retry.py
"""重试策略

本模块提供智能重试机制，用于处理网络爬取中的临时性故障：
- 可配置的最大重试次数
- 指数退避延迟算法（避免频繁重试）
- 针对不同异常类型的处理策略
- 保证最终失败时抛出原始异常

使用场景：
- 网络临时中断
- 服务器临时不可用（503）
- 超时错误
- 反爬虫检测（需要等待后重试）

使用示例：
    >>> from scraper.core.retry import RetryStrategy
    >>>
    >>> # 创建重试策略：最多重试 3 次，每次延迟翻倍
    >>> retry = RetryStrategy(
    ...     max_retries=3,
    ...     base_delay=2.0,     # 第1次等2秒，第2次等4秒，第3次等8秒
    ...     exponential=True
    ... )
    >>>
    >>> # 使用重试策略执行函数
    >>> async def fetch_page(url):
    ...     # 可能失败的爬取操作
    ...     response = await httpx.get(url)
    ...     return response.text
    >>>
    >>> # 自动重试，直到成功或耗尽重试次数
    >>> result = await retry.execute_with_retry(fetch_page, "https://example.com")
"""
import asyncio
from typing import Callable, TypeVar, Any
from scraper.exceptions import NetworkException, AntiBotDetection

# 泛型类型变量，表示函数的返回值类型
T = TypeVar('T')


class RetryStrategy:
    """重试策略类

    提供智能的重试机制来处理临时性故障，支持：
    - 可配置的重试次数（默认 3 次）
    - 灵活的延迟策略（固定延迟 vs 指数退避）
    - 异常类型识别（网络错误、反爬虫检测等）

    重试策略：
    1. 首次尝试失败后，等待一段时间再重试
    2. 如果使用指数退避，每次重试的延迟时间加倍
    3. 达到最大重试次数后，抛出最后一次的异常

    指数退避示例（base_delay=2）：
    - 第 1 次重试前：等待 2 秒
    - 第 2 次重试前：等待 4 秒
    - 第 3 次重试前：等待 8 秒

    属性：
        max_retries (int): 最大重试次数
        base_delay (float): 基础延迟时间（秒）
        exponential (bool): 是否使用指数退避

    示例：
        >>> # 快速重试策略（固定延迟）
        >>> quick_retry = RetryStrategy(
        ...     max_retries=2,
        ...     base_delay=1.0,
        ...     exponential=False  # 每次都等待 1 秒
        ... )
        >>>
        >>> # 温和重试策略（指数退避）
        >>> gentle_retry = RetryStrategy(
        ...     max_retries=5,
        ...     base_delay=3.0,
        ...     exponential=True  # 3秒 -> 6秒 -> 12秒 -> 24秒 -> 48秒
        ... )
    """

    def __init__(self, max_retries: int = 3, base_delay: float = 2.0, exponential: bool = True):
        """初始化重试策略

        参数：
            max_retries: 最大重试次数，默认 3 次
                - 设置为 0 表示不重试，失败即抛出异常
                - 设置为 1 表示最多重试 1 次（总共尝试 2 次）
                - 推荐值：2-5 次
            base_delay: 基础延迟时间（秒），默认 2.0 秒
                - 固定延迟模式：每次重试都等待这个时间
                - 指数退避模式：第 N 次重试等待 base_delay * 2^N 秒
                - 推荐值：1.0-5.0 秒
            exponential: 是否使用指数退避，默认 True
                - True: 延迟时间指数增长（适合服务器过载场景）
                - False: 延迟时间固定（适合网络抖动场景）

        示例：
            >>> # 网络抖动场景：快速重试 3 次
            >>> network_retry = RetryStrategy(
            ...     max_retries=3,
            ...     base_delay=1.0,
            ...     exponential=False
            ... )
            >>>
            >>> # 服务器过载场景：温和重试，逐渐增加间隔
            >>> server_retry = RetryStrategy(
            ...     max_retries=5,
            ...     base_delay=2.0,
            ...     exponential=True
            ... )
            >>>
            >>> # 不重试：失败即报错
            >>> no_retry = RetryStrategy(max_retries=0)
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.exponential = exponential

    async def execute_with_retry(
        self,
        func: Callable[..., T],
        *args: Any,
        **kwargs: Any
    ) -> T:
        """使用重试逻辑执行函数

        自动捕获异常并重试，直到：
        - 函数成功执行（返回结果）
        - 达到最大重试次数（抛出最后一次异常）

        重试的异常类型：
        - NetworkException: 网络相关错误（连接超时、DNS 失败等）
        - AntiBotDetection: 反爬虫检测（Cloudflare、验证码等）
        - Exception: 其他所有异常（通用重试）

        执行流程：
        1. 尝试执行函数
        2. 如果成功，直接返回结果
        3. 如果失败：
           a. 检查是否还有重试次数
           b. 如果有，计算延迟时间并等待
           c. 重新执行第 1 步
        4. 如果耗尽重试次数，抛出最后一次的异常

        参数：
            func: 要执行的异步函数
                - 必须是 async def 定义的函数
                - 可以接受任意参数
            *args: 传递给函数的位置参数
            **kwargs: 传递给函数的关键字参数

        返回：
            T: 函数的返回值（类型由函数决定）

        异常：
            Exception: 如果所有重试都失败，抛出最后一次的异常

        示例 1 - 重试网络请求：
            >>> async def fetch_url(url: str) -> str:
            ...     async with httpx.AsyncClient() as client:
            ...         response = await client.get(url)
            ...         return response.text
            >>>
            >>> retry = RetryStrategy(max_retries=3, base_delay=2.0)
            >>> try:
            ...     html = await retry.execute_with_retry(
            ...         fetch_url,
            ...         "https://example.com"
            ...     )
            ...     print("成功获取页面")
            ... except Exception as e:
            ...     print(f"所有重试都失败了: {e}")

        示例 2 - 重试爬虫操作：
            >>> from scraper.mcp_server.tools import scrape_url_tool
            >>>
            >>> # 创建重试策略
            >>> retry = RetryStrategy(
            ...     max_retries=5,      # 最多重试 5 次
            ...     base_delay=3.0,     # 从 3 秒开始
            ...     exponential=True    # 指数退避
            ... )
            >>>
            >>> # 使用重试策略爬取页面
            >>> result = await retry.execute_with_retry(
            ...     scrape_url_tool,
            ...     url="https://difficult-site.com",
            ...     content_types=["html"]
            ... )
            >>> # 如果成功，result 包含爬取结果
            >>> # 如果失败，会抛出异常

        示例 3 - 自定义函数重试：
            >>> async def process_data(data_id: int) -> dict:
            ...     # 可能失败的数据处理操作
            ...     result = await database.query(data_id)
            ...     return result
            >>>
            >>> retry = RetryStrategy(max_retries=2)
            >>> data = await retry.execute_with_retry(
            ...     process_data,
            ...     data_id=123
            ... )
        """
        # 保存最后一次的异常，用于最终抛出
        last_exception = None

        # 尝试执行 max_retries + 1 次
        # 例如：max_retries=3 时，range(4) = [0, 1, 2, 3]
        # 即：首次尝试 + 3 次重试 = 总共 4 次尝试
        for attempt in range(self.max_retries + 1):
            try:
                # 执行函数
                # await 因为我们处理的是异步函数
                return await func(*args, **kwargs)

            except (NetworkException, AntiBotDetection, Exception) as e:
                # 捕获异常，准备重试
                last_exception = e

                # 检查是否已经是最后一次尝试
                # 如果是，不再重试，跳出循环抛出异常
                if attempt == self.max_retries:
                    break

                # 计算延迟时间
                if self.exponential:
                    # 指数退避：2^0=1, 2^1=2, 2^2=4, 2^3=8...
                    # 例如：base_delay=2，则延迟为 2, 4, 8, 16 秒
                    delay = self.base_delay * (2 ** attempt)
                else:
                    # 固定延迟：每次都是 base_delay
                    delay = self.base_delay

                # 等待指定的延迟时间后再重试
                # 这给服务器/网络恢复的时间
                await asyncio.sleep(delay)

        # 所有重试都失败了
        # 抛出最后一次捕获的异常
        raise last_exception

    def get_delay(self, attempt: int) -> float:
        """计算指定尝试次数的延迟时间

        用于查询或显示延迟时间，不执行实际的等待。

        参数：
            attempt: 尝试次数（从 0 开始）
                - 0: 第一次重试前的延迟
                - 1: 第二次重试前的延迟
                - 2: 第三次重试前的延迟
                - ...

        返回：
            float: 延迟时间（秒）

        示例：
            >>> # 固定延迟策略
            >>> retry = RetryStrategy(base_delay=3.0, exponential=False)
            >>> for i in range(3):
            ...     delay = retry.get_delay(i)
            ...     print(f"第 {i+1} 次重试前等待: {delay} 秒")
            第 1 次重试前等待: 3.0 秒
            第 2 次重试前等待: 3.0 秒
            第 3 次重试前等待: 3.0 秒
            >>>
            >>> # 指数退避策略
            >>> retry = RetryStrategy(base_delay=2.0, exponential=True)
            >>> for i in range(4):
            ...     delay = retry.get_delay(i)
            ...     print(f"第 {i+1} 次重试前等待: {delay} 秒")
            第 1 次重试前等待: 2.0 秒
            第 2 次重试前等待: 4.0 秒
            第 3 次重试前等待: 8.0 秒
            第 4 次重试前等待: 16.0 秒
        """
        if self.exponential:
            # 指数退避：延迟时间指数增长
            return self.base_delay * (2 ** attempt)
        # 固定延迟：延迟时间保持不变
        return self.base_delay
