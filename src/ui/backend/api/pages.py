"""页面路由"""

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from ..config import TEMPLATES_DIR

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """主页（Dashboard）"""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/chat", response_class=HTMLResponse)
async def chat(request: Request):
    """聊天页面"""
    return templates.TemplateResponse("chat.html", {"request": request})


@router.get("/config", response_class=HTMLResponse)
async def config(request: Request):
    """配置管理页面"""
    return templates.TemplateResponse("config.html", {"request": request})


@router.get("/data", response_class=HTMLResponse)
async def data_management(request: Request):
    """数据管理页面"""
    return templates.TemplateResponse("manage.html", {"request": request})


@router.get("/structure", response_class=HTMLResponse)
async def structure_editor(request: Request):
    """文档结构编辑器页面"""
    return templates.TemplateResponse("structure_editor.html", {"request": request})


@router.get("/briefs", response_class=HTMLResponse)
async def briefs_page(request: Request):
    """每日简报加载页面"""
    return templates.TemplateResponse("briefs.html", {"request": request})


@router.get("/memory", response_class=HTMLResponse)
async def memory_page(request: Request):
    """LLM-Memory 简报记忆浏览/对话页面（桥接外部 LLM-Memory webui）"""
    return templates.TemplateResponse("memory.html", {"request": request})
