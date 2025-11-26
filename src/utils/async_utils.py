"""
异步并行处理工具模块

提供通用的异步并行处理功能，与业务逻辑无关。
"""

import asyncio
import logging
from typing import Any, Callable, List, TypeVar, Coroutine

import nest_asyncio

logger = logging.getLogger(__name__)

# 泛型类型定义
T = TypeVar('T')
R = TypeVar('R')


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """
    在同步上下文中运行异步协程
    
    自动处理事件循环的各种情况：
    - 如果没有运行中的事件循环，使用 asyncio.run()
    - 如果已有运行中的事件循环（如 FastAPI），使用 nest_asyncio
    
    Args:
        coro: 要执行的异步协程
        
    Returns:
        协程的返回值
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 如果事件循环已在运行（如在 FastAPI 中），应用 nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        else:
            return asyncio.run(coro)
    except RuntimeError:
        # 备用方案：直接使用 asyncio.run
        return asyncio.run(coro)


async def parallel_process(
    items: List[T],
    processor: Callable[[T], Coroutine[Any, Any, R]],
    max_concurrent: int = 5,
    return_exceptions: bool = True
) -> List[R]:
    """
    通用并行处理函数
    
    使用信号量控制并发数，并行处理多个项目。
    
    Args:
        items: 要处理的项目列表
        processor: 异步处理函数，接收单个项目，返回处理结果
        max_concurrent: 最大并发数（默认5，避免API限流）
        return_exceptions: 是否将异常作为结果返回，而不是抛出
        
    Returns:
        处理结果列表（与输入顺序一致）
        
    Example:
        async def process_item(item):
            return await some_async_operation(item)
            
        results = await parallel_process(items, process_item, max_concurrent=5)
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_with_semaphore(item: T) -> R:
        async with semaphore:
            return await processor(item)
    
    tasks = [process_with_semaphore(item) for item in items]
    results = await asyncio.gather(*tasks, return_exceptions=return_exceptions)
    
    return results


async def parallel_process_with_filter(
    items: List[T],
    processor: Callable[[T], Coroutine[Any, Any, R]],
    max_concurrent: int = 5
) -> List[R]:
    """
    并行处理并过滤掉异常结果
    
    Args:
        items: 要处理的项目列表
        processor: 异步处理函数
        max_concurrent: 最大并发数
        
    Returns:
        成功处理的结果列表（过滤掉异常）
    """
    results = await parallel_process(items, processor, max_concurrent, return_exceptions=True)
    
    valid_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"项目 {i} 处理失败: {result}")
        else:
            valid_results.append(result)
    
    return valid_results
