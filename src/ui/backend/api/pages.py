"""页面路由"""

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse

from ..config import settings

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.templates_dir))


@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """主页面"""
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """聊天页面"""
    return templates.TemplateResponse("chat.html", {"request": request})


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    """配置管理页面"""
    return templates.TemplateResponse("config.html", {"request": request})


@router.get("/data", response_class=HTMLResponse)
async def data_page(request: Request):
    """数据管理页面"""
    return templates.TemplateResponse("data.html", {"request": request})


@router.get("/chapters", response_class=HTMLResponse)
async def chapters_page(request: Request):
    """章节管理页面"""
    return templates.TemplateResponse("chapters.html", {"request": request})


@router.get("/favicon.ico")
async def favicon():
    """网站图标"""
    favicon_path = settings.static_dir / "favicon.ico"
    return FileResponse(str(favicon_path))