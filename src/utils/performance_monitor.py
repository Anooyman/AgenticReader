"""
性能监控工具

提供函数执行时间监控、内存使用跟踪、系统资源监控等功能
"""
import time
import functools
import logging
import psutil
import threading
from typing import Any, Callable, Dict, List, Optional, TypeVar
from contextlib import contextmanager
from dataclasses import dataclass, field
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])


@dataclass
class PerformanceMetric:
    """性能指标数据类"""
    function_name: str
    execution_time: float
    memory_before: float
    memory_after: float
    memory_peak: float
    cpu_percent: float
    timestamp: float
    args_hash: str = ""
    kwargs_hash: str = ""
    return_size: int = 0
    exception_occurred: bool = False


@dataclass
class SystemMetrics:
    """系统指标数据类"""
    cpu_percent: float
    memory_percent: float
    memory_available_mb: float
    disk_usage_percent: float
    disk_free_gb: float
    active_threads: int
    timestamp: float


class PerformanceMonitor:
    """性能监控器主类"""

    def __init__(self, max_metrics: int = 1000):
        """
        初始化性能监控器

        Args:
            max_metrics: 保存的最大指标数量
        """
        self.metrics: deque = deque(maxlen=max_metrics)
        self.system_metrics: deque = deque(maxlen=max_metrics)
        self.function_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            'total_calls': 0,
            'total_time': 0.0,
            'avg_time': 0.0,
            'min_time': float('inf'),
            'max_time': 0.0,
            'error_count': 0,
            'last_call': 0.0
        })
        self._monitoring = False
        self._monitor_thread = None

    def start_system_monitoring(self, interval: float = 5.0):
        """
        启动系统监控

        Args:
            interval: 监控间隔（秒）
        """
        if self._monitoring:
            logger.warning("系统监控已在运行")
            return

        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_system_metrics,
            args=(interval,),
            daemon=True
        )
        self._monitor_thread.start()
        logger.info(f"系统监控已启动，间隔: {interval}秒")

    def stop_system_monitoring(self):
        """停止系统监控"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
        logger.info("系统监控已停止")

    def _monitor_system_metrics(self, interval: float):
        """系统指标监控循环"""
        while self._monitoring:
            try:
                # 获取系统指标
                cpu_percent = psutil.cpu_percent(interval=0.1)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')

                metric = SystemMetrics(
                    cpu_percent=cpu_percent,
                    memory_percent=memory.percent,
                    memory_available_mb=memory.available / (1024 * 1024),
                    disk_usage_percent=disk.percent,
                    disk_free_gb=disk.free / (1024 * 1024 * 1024),
                    active_threads=threading.active_count(),
                    timestamp=time.time()
                )

                self.system_metrics.append(metric)

                # 检查资源警告
                self._check_resource_warnings(metric)

                time.sleep(interval)

            except Exception as e:
                logger.error(f"系统监控出错: {e}")
                time.sleep(interval)

    def _check_resource_warnings(self, metric: SystemMetrics):
        """检查资源使用警告"""
        if metric.cpu_percent > 90:
            logger.warning(f"CPU使用率过高: {metric.cpu_percent:.1f}%")

        if metric.memory_percent > 90:
            logger.warning(f"内存使用率过高: {metric.memory_percent:.1f}%")

        if metric.disk_usage_percent > 90:
            logger.warning(f"磁盘使用率过高: {metric.disk_usage_percent:.1f}%")

    def add_metric(self, metric: PerformanceMetric):
        """添加性能指标"""
        self.metrics.append(metric)

        # 更新函数统计
        stats = self.function_stats[metric.function_name]
        stats['total_calls'] += 1
        stats['total_time'] += metric.execution_time
        stats['avg_time'] = stats['total_time'] / stats['total_calls']
        stats['min_time'] = min(stats['min_time'], metric.execution_time)
        stats['max_time'] = max(stats['max_time'], metric.execution_time)
        stats['last_call'] = metric.timestamp

        if metric.exception_occurred:
            stats['error_count'] += 1

    def get_function_stats(self, function_name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取函数统计信息

        Args:
            function_name: 函数名，为None则返回所有函数统计

        Returns:
            函数统计信息
        """
        if function_name:
            return dict(self.function_stats.get(function_name, {}))
        return dict(self.function_stats)

    def get_slow_functions(self, threshold: float = 1.0, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取执行时间较长的函数

        Args:
            threshold: 时间阈值（秒）
            limit: 返回数量限制

        Returns:
            慢函数列表
        """
        slow_functions = []

        for func_name, stats in self.function_stats.items():
            if stats['avg_time'] > threshold:
                slow_functions.append({
                    'function_name': func_name,
                    'avg_time': stats['avg_time'],
                    'max_time': stats['max_time'],
                    'total_calls': stats['total_calls'],
                    'total_time': stats['total_time']
                })

        # 按平均时间排序
        slow_functions.sort(key=lambda x: x['avg_time'], reverse=True)
        return slow_functions[:limit]

    def get_memory_usage_report(self) -> Dict[str, Any]:
        """获取内存使用报告"""
        if not self.metrics:
            return {"error": "没有性能数据"}

        memory_data = [(m.memory_before, m.memory_after, m.memory_peak) for m in self.metrics]

        return {
            "total_samples": len(memory_data),
            "avg_memory_before": sum(m[0] for m in memory_data) / len(memory_data),
            "avg_memory_after": sum(m[1] for m in memory_data) / len(memory_data),
            "max_memory_peak": max(m[2] for m in memory_data),
            "memory_unit": "MB"
        }

    def get_system_health_report(self) -> Dict[str, Any]:
        """获取系统健康报告"""
        if not self.system_metrics:
            return {"error": "没有系统监控数据"}

        recent_metrics = list(self.system_metrics)[-10:]  # 最近10个样本

        return {
            "avg_cpu_percent": sum(m.cpu_percent for m in recent_metrics) / len(recent_metrics),
            "avg_memory_percent": sum(m.memory_percent for m in recent_metrics) / len(recent_metrics),
            "min_memory_available_mb": min(m.memory_available_mb for m in recent_metrics),
            "avg_disk_usage_percent": sum(m.disk_usage_percent for m in recent_metrics) / len(recent_metrics),
            "min_disk_free_gb": min(m.disk_free_gb for m in recent_metrics),
            "max_active_threads": max(m.active_threads for m in recent_metrics),
            "samples_count": len(recent_metrics)
        }

    def clear_metrics(self):
        """清空所有指标"""
        self.metrics.clear()
        self.system_metrics.clear()
        self.function_stats.clear()
        logger.info("性能指标已清空")


# 全局性能监控器实例
global_monitor = PerformanceMonitor()


def monitor_performance(include_args: bool = False, include_memory: bool = True):
    """
    性能监控装饰器

    Args:
        include_args: 是否包含参数信息
        include_memory: 是否监控内存使用

    Returns:
        装饰后的函数
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import sys
            import hashlib

            # 记录开始状态
            start_time = time.time()
            memory_before = psutil.Process().memory_info().rss / (1024 * 1024) if include_memory else 0
            cpu_before = psutil.cpu_percent()

            exception_occurred = False
            result = None

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                exception_occurred = True
                raise
            finally:
                # 记录结束状态
                end_time = time.time()
                execution_time = end_time - start_time
                memory_after = psutil.Process().memory_info().rss / (1024 * 1024) if include_memory else 0
                memory_peak = max(memory_before, memory_after)
                cpu_after = psutil.cpu_percent()

                # 计算参数哈希
                args_hash = ""
                kwargs_hash = ""
                if include_args:
                    try:
                        args_str = str(args)[:100]  # 限制长度
                        kwargs_str = str(kwargs)[:100]
                        args_hash = hashlib.md5(args_str.encode()).hexdigest()[:8]
                        kwargs_hash = hashlib.md5(kwargs_str.encode()).hexdigest()[:8]
                    except:
                        pass

                # 计算返回值大小
                return_size = 0
                if result is not None:
                    try:
                        return_size = sys.getsizeof(result)
                    except:
                        pass

                # 创建性能指标
                metric = PerformanceMetric(
                    function_name=f"{func.__module__}.{func.__name__}",
                    execution_time=execution_time,
                    memory_before=memory_before,
                    memory_after=memory_after,
                    memory_peak=memory_peak,
                    cpu_percent=(cpu_before + cpu_after) / 2,
                    timestamp=start_time,
                    args_hash=args_hash,
                    kwargs_hash=kwargs_hash,
                    return_size=return_size,
                    exception_occurred=exception_occurred
                )

                # 添加到全局监控器
                global_monitor.add_metric(metric)

                # 记录慢函数警告
                if execution_time > 5.0:  # 超过5秒的函数
                    logger.warning(f"慢函数检测: {metric.function_name} 执行时间 {execution_time:.2f}秒")

        return wrapper
    return decorator


@contextmanager
def performance_context(context_name: str, log_result: bool = True):
    """
    性能监控上下文管理器

    Args:
        context_name: 上下文名称
        log_result: 是否记录结果日志

    Yields:
        性能指标字典
    """
    start_time = time.time()
    memory_before = psutil.Process().memory_info().rss / (1024 * 1024)

    performance_data = {
        'context_name': context_name,
        'start_time': start_time
    }

    try:
        yield performance_data
    finally:
        end_time = time.time()
        execution_time = end_time - start_time
        memory_after = psutil.Process().memory_info().rss / (1024 * 1024)

        performance_data.update({
            'execution_time': execution_time,
            'memory_before': memory_before,
            'memory_after': memory_after,
            'memory_delta': memory_after - memory_before
        })

        if log_result:
            logger.info(f"性能上下文 '{context_name}': "
                       f"耗时 {execution_time:.3f}秒, "
                       f"内存变化 {memory_after - memory_before:+.2f}MB")


def get_performance_summary() -> Dict[str, Any]:
    """获取性能监控总结"""
    return {
        "function_stats": global_monitor.get_function_stats(),
        "slow_functions": global_monitor.get_slow_functions(),
        "memory_report": global_monitor.get_memory_usage_report(),
        "system_health": global_monitor.get_system_health_report(),
        "metrics_count": len(global_monitor.metrics),
        "system_metrics_count": len(global_monitor.system_metrics)
    }


def start_monitoring(interval: float = 5.0):
    """启动全局性能监控"""
    global_monitor.start_system_monitoring(interval)


def stop_monitoring():
    """停止全局性能监控"""
    global_monitor.stop_system_monitoring()


# 导出主要接口
__all__ = [
    'PerformanceMonitor',
    'PerformanceMetric',
    'SystemMetrics',
    'monitor_performance',
    'performance_context',
    'get_performance_summary',
    'start_monitoring',
    'stop_monitoring',
    'global_monitor'
]