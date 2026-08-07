"""页面路由"""

import json

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from ..config import TEMPLATES_DIR
from src.pipeline.qa_labels import QA_LABELS

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


@router.get("/report", response_class=HTMLResponse)
async def report_page(request: Request):
    """论文/文章摘要卡片浏览页面"""
    return templates.TemplateResponse("report.html", {
        "request": request,
        "qa_labels_json": json.dumps(QA_LABELS, ensure_ascii=False),
    })


@router.get("/briefs", response_class=HTMLResponse)
async def briefs_page(request: Request):
    """每日简报加载页面"""
    return templates.TemplateResponse("briefs.html", {"request": request})
