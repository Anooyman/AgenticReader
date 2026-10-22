"""配置文件"""

import logging
import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# UI 目录
UI_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = UI_DIR / "templates"
STATIC_DIR = UI_DIR / "static"

# 数据目录
DATA_DIR = PROJECT_ROOT / "data"
PDF_DIR = DATA_DIR / "pdf"
JSON_DATA_DIR = DATA_DIR / "json_data"
VECTOR_DB_DIR = DATA_DIR / "vector_db"
PDF_IMAGE_DIR = DATA_DIR / "pdf_image"
OUTPUT_DIR = DATA_DIR / "output"

# 应用配置
APP_NAME = "AgenticReader"
APP_VERSION = "2.0.0"
DEBUG = True

# CORS
# 本地应用默认只放行本地前端来源；可用环境变量 CORS_ORIGINS（逗号分隔）覆盖
DEFAULT_CORS_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

CORS_ORIGINS = [
    origin.strip()
    for origin in (os.environ.get("CORS_ORIGINS") or "").split(",")
    if origin.strip()
] or DEFAULT_CORS_ORIGINS

# 通配来源 + allow_credentials 是危险组合：出现通配符时直接关闭 credentials，
# 确保该组合在任何配置下都不会生效（app.py 挂载 CORS 中间件时使用本标志）
CORS_ALLOW_CREDENTIALS = "*" not in CORS_ORIGINS
if not CORS_ALLOW_CREDENTIALS:
    logging.warning(
        "CORS_ORIGINS 包含通配符 \"*\"，已自动关闭 allow_credentials，"
        "建议改用本地来源或显式配置的来源列表"
    )
