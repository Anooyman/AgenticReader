"""日志配置"""

import logging
import sys
from typing import Dict, Any

from .settings import settings


def setup_logging() -> None:
    """设置应用日志配置"""

    # 日志级别映射
    level_mapping = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    # 获取日志级别
    log_level = level_mapping.get(settings.log_level.upper(), logging.INFO)

    # 配置根日志器
    logging.basicConfig(
        level=log_level,
        format=settings.log_format,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # 配置特定模块的日志级别
    loggers_config = {
        "uvicorn": logging.WARNING,
        "uvicorn.error": logging.INFO,
        "uvicorn.access": logging.WARNING,
        "fastapi": logging.INFO,
    }

    for logger_name, level in loggers_config.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志器"""
    return logging.getLogger(name)