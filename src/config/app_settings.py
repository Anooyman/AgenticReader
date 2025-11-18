"""
统一应用配置模块 - Pydantic BaseSettings

该模块提供了统一的应用配置管理，同时保持与原有配置系统的向后兼容性。
支持从环境变量和 .env 文件中加载配置，避免配置重复。

主要特点：
1. 使用 Pydantic 进行类型检验和验证
2. 支持环境变量覆盖
3. 自动创建必要的数据目录
4. 提供统一的配置接口
5. 保持与原有配置的兼容性

Author: LLMReader Team
Date: 2025-09-03
Version: 1.0
"""

import os
import pathlib
from typing import Optional, Dict, List, Any
from dotenv import load_dotenv

# 根据环境判断使用哪个 pydantic 版本
try:
    from pydantic_settings import BaseSettings
    from pydantic import Field
except ImportError:
    from pydantic import BaseSettings, Field


# 加载环境变量
load_dotenv()


class AppSettings(BaseSettings):
    """
    统一的应用配置类
    
    包含所有应用级别的配置，支持从环境变量和 .env 文件读取。
    Attributes:
        app_name: 应用名称
        app_version: 应用版本
        debug: 调试模式
        host: 服务器主机地址
        port: 服务器端口
        reload: 是否启用热重载
        project_root: 项目根目录路径
        data_dir: 数据存储根目录
        log_level: 日志级别
        default_provider: 默认LLM提供商
    """
    
    # === 基础配置 ===
    app_name: str = Field(default="LLMReader", env="APP_NAME")
    app_version: str = Field(default="1.0.0", env="APP_VERSION")
    debug: bool = Field(default=False, env="DEBUG")
    
    # === 服务器配置 ===
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT")
    reload: bool = Field(default=True, env="RELOAD")
    
    # === 路径配置 ===
    project_root: pathlib.Path = Field(
        default_factory=lambda: pathlib.Path(__file__).resolve().parents[2],
        env="PROJECT_ROOT"
    )
    data_dir: pathlib.Path = Field(
        default_factory=lambda: pathlib.Path(__file__).resolve().parents[2] / "data",
        env="DATA_DIR"
    )
    
    # === 数据子目录 ===
    pdf_dir: Optional[pathlib.Path] = None
    pdf_image_dir: Optional[pathlib.Path] = None
    json_data_dir: Optional[pathlib.Path] = None
    vector_db_dir: Optional[pathlib.Path] = None
    output_dir: Optional[pathlib.Path] = None
    memory_dir: Optional[pathlib.Path] = None
    sessions_dir: Optional[pathlib.Path] = None
    
    # === LLM 配置 ===
    default_provider: str = Field(default="openai", env="DEFAULT_PROVIDER")
    default_pdf_preset: str = Field(default="high", env="DEFAULT_PDF_PRESET")
    
    # === 会话配置 ===
    session_cleanup_enabled: bool = Field(default=True, env="SESSION_CLEANUP_ENABLED")
    session_max_age_hours: int = Field(default=168, env="SESSION_MAX_AGE_HOURS")  # 7天
    auto_save_enabled: bool = Field(default=True, env="AUTO_SAVE_ENABLED")
    max_backup_files: int = Field(default=10, env="MAX_BACKUP_FILES")
    
    # === CORS 配置 ===
    cors_origins: List[str] = Field(default=["*"], env="CORS_ORIGINS")
    cors_credentials: bool = Field(default=True, env="CORS_CREDENTIALS")
    
    # === 日志配置 ===
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        env="LOG_FORMAT"
    )
    
    # === Web UI 配置 ===
    static_dir: Optional[pathlib.Path] = None
    templates_dir: Optional[pathlib.Path] = None
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # 初始化所有数据子目录
        self._init_data_directories()
        
        # 初始化 Web UI 目录
        if self.static_dir is None:
            self.static_dir = self.project_root / "src" / "ui" / "static"
        if self.templates_dir is None:
            self.templates_dir = self.project_root / "src" / "ui" / "templates"

    def _init_data_directories(self) -> None:
        """
        初始化所有数据子目录
        
        根据 data_dir 自动创建所有必要的子目录结构
        """
        # 设置子目录路径
        subdirs = {
            "pdf_dir": "pdf",
            "pdf_image_dir": "pdf_image",
            "json_data_dir": "json_data",
            "vector_db_dir": "vector_db",
            "output_dir": "output",
            "memory_dir": "memory",
            "sessions_dir": "sessions",
        }
        
        for attr_name, subdir in subdirs.items():
            if getattr(self, attr_name) is None:
                setattr(self, attr_name, self.data_dir / subdir)
        
        # 确保所有目录都存在
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """
        确保所有必要的目录存在
        
        创建数据目录及其所有子目录，以及会话备份/导出目录
        """
        directories = [
            self.data_dir,
            self.pdf_dir,
            self.pdf_image_dir,
            self.json_data_dir,
            self.vector_db_dir,
            self.output_dir,
            self.memory_dir,
            self.sessions_dir,
            self.sessions_dir / "backups",
            self.sessions_dir / "exports",
            self.static_dir,
            self.templates_dir,
        ]
        
        for directory in directories:
            if directory is not None:
                directory.mkdir(parents=True, exist_ok=True)

    def get_data_paths(self) -> Dict[str, pathlib.Path]:
        """
        获取所有数据路径的字典
        
        Returns:
            Dict[str, pathlib.Path]: 包含所有数据目录路径的字典
        """
        return {
            "data": self.data_dir,
            "pdf": self.pdf_dir,
            "pdf_image": self.pdf_image_dir,
            "json_data": self.json_data_dir,
            "vector_db": self.vector_db_dir,
            "output": self.output_dir,
            "memory": self.memory_dir,
            "sessions": self.sessions_dir,
        }

    def get_llm_config(self) -> Dict[str, Any]:
        """
        获取 LLM 配置字典
        
        Returns:
            Dict[str, Any]: LLM 相关配置信息
        """
        return {
            "provider": self.default_provider,
            "pdf_preset": self.default_pdf_preset,
        }


# === 全局配置实例 ===
settings = AppSettings()


# === 向后兼容性 - 导出常用路径 ===
DATA_DIR = settings.data_dir
PDF_DIR = settings.pdf_dir
PDF_IMAGE_DIR = settings.pdf_image_dir
JSON_DATA_DIR = settings.json_data_dir
VECTOR_DB_DIR = settings.vector_db_dir
OUTPUT_DIR = settings.output_dir
MEMORY_DIR = settings.memory_dir
SESSIONS_DIR = settings.sessions_dir

PROJECT_ROOT = settings.project_root

# 应用配置
APP_NAME = settings.app_name
APP_VERSION = settings.app_version
DEBUG = settings.debug

# LLM 配置
DEFAULT_PROVIDER = settings.default_provider
DEFAULT_PDF_PRESET = settings.default_pdf_preset
