"""通用工具函数"""

import os
from pathlib import Path


def ensure_data_dirs():
    """确保数据目录存在（兼容旧代码）"""
    directories = [
        "data",
        "data/pdf",
        "data/json_data",
        "data/pdf_image",
        "data/vector_db",
        "data/output",
        "data/sessions",
        "data/sessions/backups",
        "data/sessions/exports",
    ]

    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)


def get_pdf_name(filename: str) -> str:
    """从文件名获取PDF基础名称（兼容旧代码）"""
    return Path(filename).stem