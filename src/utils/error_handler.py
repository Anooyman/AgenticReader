"""
错误处理和异常管理工具

提供统一的错误处理、日志记录和异常恢复机制
"""
import logging
import traceback
import functools
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union
from contextlib import contextmanager

from .exceptions import (
    LLMReaderBaseException,
    ConfigurationError,
    FileProcessingError,
    LLMServiceError,
    NetworkError,
    ValidationError
)

# 创建模块级别的日志记录器
logger = logging.getLogger(__name__)

# 类型变量定义
F = TypeVar('F', bound=Callable[..., Any])


class ErrorHandler:
    """统一错误处理器"""

    def __init__(self, logger_name: Optional[str] = None):
        """
        初始化错误处理器

        Args:
            logger_name: 自定义日志记录器名称
        """
        self.logger = logging.getLogger(logger_name or __name__)
        self.error_counts = {}

    def handle_error(self,
                    error: Exception,
                    context: str = "",
                    reraise: bool = True,
                    fallback_value: Any = None) -> Any:
        """
        处理错误的通用方法

        Args:
            error: 捕获的异常
            context: 错误上下文信息
            reraise: 是否重新抛出异常
            fallback_value: 发生错误时的回退值

        Returns:
            如果不重新抛出异常，返回fallback_value

        Raises:
            根据reraise参数决定是否抛出异常
        """
        error_key = f"{type(error).__name__}:{context}"
        self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1

        self.logger.error(
            f"错误处理 - 上下文: {context}, "
            f"异常类型: {type(error).__name__}, "
            f"错误消息: {str(error)}, "
            f"发生次数: {self.error_counts[error_key]}"
        )

        # 记录详细的错误堆栈信息（仅在DEBUG模式下）
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"错误堆栈:\n{traceback.format_exc()}")

        if reraise:
            raise error

        return fallback_value

    def get_error_statistics(self) -> Dict[str, int]:
        """
        获取错误统计信息

        Returns:
            错误类型及其发生次数的字典
        """
        return self.error_counts.copy()


def retry_on_error(max_retries: int = 3,
                  delay: float = 1.0,
                  backoff_factor: float = 2.0,
                  exceptions: tuple = (Exception,)) -> Callable[[F], F]:
    """
    重试装饰器，在指定异常发生时自动重试

    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff_factor: 延迟递增因子
        exceptions: 需要重试的异常类型元组

    Returns:
        装饰后的函数
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import time

            last_exception = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        logger.error(
                            f"函数 {func.__name__} 在 {max_retries} 次重试后仍然失败: {e}"
                        )
                        break

                    logger.warning(
                        f"函数 {func.__name__} 第 {attempt + 1} 次尝试失败: {e}，"
                        f"{current_delay:.1f}秒后重试"
                    )

                    time.sleep(current_delay)
                    current_delay *= backoff_factor

            raise last_exception

        return wrapper
    return decorator


def safe_execute(func: Callable,
                *args,
                default_value: Any = None,
                context: str = "",
                log_errors: bool = True,
                **kwargs) -> Any:
    """
    安全执行函数，捕获异常并返回默认值

    Args:
        func: 要执行的函数
        *args: 函数的位置参数
        default_value: 发生异常时返回的默认值
        context: 错误上下文
        log_errors: 是否记录错误日志
        **kwargs: 函数的关键字参数

    Returns:
        函数执行结果或默认值
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_errors:
            logger.error(f"安全执行失败 - {context}: {e}")
        return default_value


@contextmanager
def error_context(context_name: str,
                 reraise: bool = True,
                 cleanup_func: Optional[Callable] = None):
    """
    错误上下文管理器，提供统一的错误处理和清理机制

    Args:
        context_name: 上下文名称
        reraise: 是否重新抛出异常
        cleanup_func: 清理函数

    Yields:
        ErrorHandler实例
    """
    error_handler = ErrorHandler()

    try:
        logger.debug(f"进入错误上下文: {context_name}")
        yield error_handler
        logger.debug(f"成功退出错误上下文: {context_name}")

    except Exception as e:
        logger.error(f"错误上下文 {context_name} 中发生异常: {e}")

        if cleanup_func:
            try:
                cleanup_func()
                logger.info(f"错误上下文 {context_name} 清理完成")
            except Exception as cleanup_error:
                logger.error(f"清理函数执行失败: {cleanup_error}")

        if reraise:
            raise


def exception_to_llm_error(exception: Exception) -> LLMReaderBaseException:
    """
    将通用异常转换为项目特定的异常类型

    Args:
        exception: 原始异常

    Returns:
        转换后的LLMReader异常
    """
    error_message = str(exception)

    # 根据异常类型进行分类
    if isinstance(exception, (ConnectionError, TimeoutError)):
        return NetworkError(f"网络连接错误: {error_message}")

    elif isinstance(exception, (FileNotFoundError, PermissionError, OSError)):
        return FileProcessingError(f"文件操作错误: {error_message}")

    elif isinstance(exception, (ValueError, TypeError)):
        return ValidationError(f"数据验证错误: {error_message}")

    elif "config" in error_message.lower() or "setting" in error_message.lower():
        return ConfigurationError(f"配置错误: {error_message}")

    elif "llm" in error_message.lower() or "model" in error_message.lower():
        return LLMServiceError(f"LLM服务错误: {error_message}")

    else:
        # 默认转换为基础异常
        return LLMReaderBaseException(
            f"未分类错误: {error_message}",
            error_code="UNKNOWN_ERROR"
        )


class BatchErrorHandler:
    """批量操作错误处理器"""

    def __init__(self):
        self.errors: List[Dict[str, Any]] = []
        self.successful_items: List[Any] = []

    def add_error(self, item: Any, error: Exception, context: str = ""):
        """
        添加错误记录

        Args:
            item: 发生错误的项目
            error: 异常信息
            context: 错误上下文
        """
        self.errors.append({
            "item": item,
            "error": str(error),
            "error_type": type(error).__name__,
            "context": context,
            "timestamp": logging.Formatter().formatTime(logging.LogRecord(
                "", 0, "", 0, "", (), None
            ))
        })

    def add_success(self, item: Any):
        """
        添加成功处理的项目

        Args:
            item: 成功处理的项目
        """
        self.successful_items.append(item)

    def get_summary(self) -> Dict[str, Any]:
        """
        获取批量操作摘要

        Returns:
            操作摘要统计
        """
        total = len(self.errors) + len(self.successful_items)
        success_rate = (len(self.successful_items) / total * 100) if total > 0 else 0

        return {
            "total_items": total,
            "successful": len(self.successful_items),
            "failed": len(self.errors),
            "success_rate": f"{success_rate:.1f}%",
            "errors": self.errors
        }

    def log_summary(self, logger_instance: Optional[logging.Logger] = None):
        """
        记录批量操作摘要日志

        Args:
            logger_instance: 自定义日志记录器
        """
        log = logger_instance or logger
        summary = self.get_summary()

        log.info(
            f"批量操作完成 - 总数: {summary['total_items']}, "
            f"成功: {summary['successful']}, "
            f"失败: {summary['failed']}, "
            f"成功率: {summary['success_rate']}"
        )

        if self.errors:
            log.warning(f"失败项目详情: {len(self.errors)} 个错误")
            for error in self.errors[:5]:  # 只显示前5个错误
                log.warning(f"  - {error['item']}: {error['error']}")

            if len(self.errors) > 5:
                log.warning(f"  ... 还有 {len(self.errors) - 5} 个错误")


# 全局错误处理器实例
global_error_handler = ErrorHandler("LLMReader.Global")


def setup_global_exception_handler():
    """
    设置全局异常处理器
    """
    import sys

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            # 允许键盘中断正常退出
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.critical(
            "未捕获的异常",
            exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = handle_exception
    logger.info("全局异常处理器已设置")