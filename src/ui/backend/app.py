"""重构后的 FastAPI 应用主入口"""

import sys
import pathlib
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# 添加项目根路径
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from .config import settings, setup_logging
from .api.v1 import sessions, config as config_api, pdf, chat, web
from .api import websocket

# 设置日志
setup_logging()

# 创建 FastAPI 应用
app = FastAPI(
    title=settings.app_name,
    description="智能文档分析系统 API 服务",
    version=settings.app_version,
    debug=settings.debug
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件和模板
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
templates = Jinja2Templates(directory=str(settings.templates_dir))

# 注册路由
app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])
app.include_router(config_api.router, prefix="/api/v1", tags=["config"])
app.include_router(pdf.router, prefix="/api/v1", tags=["pdf"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(web.router, prefix="/api/v1", tags=["web"])
app.include_router(websocket.router, tags=["websocket"])

# 页面路由
from .api.pages import router as pages_router
app.include_router(pages_router)


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    from .config.logging import get_logger
    logger = get_logger(__name__)

    logger.info(f"🚀 {settings.app_name} v{settings.app_version} 正在启动...")
    logger.info(f"📁 项目根目录: {settings.project_root}")
    logger.info(f"📊 会话清理: {'启用' if settings.session_cleanup_enabled else '禁用'}")
    logger.info("✅ 应用启动完成")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    from .config.logging import get_logger
    logger = get_logger(__name__)

    logger.info("🛑 应用正在关闭...")
    # 这里可以添加清理逻辑
    logger.info("✅ 应用关闭完成")


# 健康检查
@app.get("/health")
async def health_check():
    """健康检查接口"""
    from datetime import datetime
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": settings.app_version
    }