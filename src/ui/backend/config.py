"""配置文件"""

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
CORS_ORIGINS = ["*"]
