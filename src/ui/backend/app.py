"""FastAPI 应用主入口"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from .config import APP_NAME, APP_VERSION, DEBUG, CORS_ORIGINS, TEMPLATES_DIR, STATIC_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    """两条独立后台车道的启停（ai-research-pipeline 合并进来的部分）：

    - 管线车道（job_runner）：处理 pdf/web 条目、生成报告。串行，因为这些
      操作都要写 pipeline_queue.json。
    - 对话入库车道（chat_ingest）：周期扫描 research chat 会话并同步进
      src.memory。只写 memory、不碰 queue，单独一条——挤在同一条队列里会
      被一个 30 分钟的 PDF 任务堵死。
    """
    print(f"🚀 {APP_NAME} v{APP_VERSION} 正在启动...")
    print(f"📁 项目根目录: {PROJECT_ROOT}")

    from .services import job_runner, chat_ingest

    job_runner.init()
    await job_runner.recover_on_startup()

    tasks = [
        asyncio.create_task(job_runner.run_forever()),
        asyncio.create_task(chat_ingest.run_forever()),
    ]

    print("✅ 应用启动完成")
    try:
        yield
    finally:
        print("🛑 应用正在关闭...")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        print("✅ 应用关闭完成")


# 创建 FastAPI 应用
app = FastAPI(
    title=APP_NAME,
    description="智能文档分析系统",
    version=APP_VERSION,
    debug=DEBUG,
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 模板
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 导入并注册路由
from .api import pages, websocket
from .api.v1 import (
    documents, chat, pdf, chapters, structure, config, sessions, data,
    report, briefs, jobs, memory,
)

app.include_router(pages.router, tags=["Pages"])
app.include_router(websocket.router, tags=["WebSocket"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])
app.include_router(pdf.router, prefix="/api/v1/pdf", tags=["PDF"])
app.include_router(chapters.router, prefix="/api/v1/chapters", tags=["Chapters"])
app.include_router(structure.router, prefix="/api/v1/structure", tags=["Structure"])
app.include_router(config.router, prefix="/api/v1/config", tags=["Config"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["Sessions"])
app.include_router(data.router, prefix="/api/v1/data", tags=["Data Management"])
app.include_router(report.router, prefix="/api/v1/report", tags=["Report"])
app.include_router(briefs.router, prefix="/api/v1/briefs", tags=["Briefs"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])
app.include_router(memory.router, prefix="/api/v1/memory", tags=["Memory"])


@app.get("/health")
async def health_check():
    """健康检查"""
    from datetime import datetime
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": APP_VERSION
    }
