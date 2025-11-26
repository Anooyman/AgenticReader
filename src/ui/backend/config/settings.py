"""
应用配置设置 - POC UI 后端配置

该模块导入统一的应用配置，避免配置重复。
所有配置现在由 src.config.app_settings 统一管理。

向后兼容性:
- 保持原有的 AppSettings 类名
- 保持原有的 settings 全局实例
- 所有原有代码无需修改即可工作

Author: LLMReader Team
Date: 2025-09-03
Version: 1.0
"""

# 导入统一的应用配置
from src.config.app_settings import AppSettings, settings

# 确保 __all__ 向后兼容
__all__ = ["AppSettings", "settings"]