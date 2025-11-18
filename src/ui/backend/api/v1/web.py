"""Web内容处理相关API端点"""

import sys
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

# 添加项目根路径到sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ...config import get_logger, settings
from ...services.chat_service import chat_service

router = APIRouter(prefix="/web", tags=["Web"])
logger = get_logger(__name__)


class WebProcessRequest(BaseModel):
    url: str
    save_outputs: bool = True


@router.post("/process")
async def process_web_url(request: WebProcessRequest):
    """处理网页URL"""
    try:
        url = request.url.strip()

        if not url or not (url.startswith('http://') or url.startswith('https://')):
            raise HTTPException(status_code=400, detail="请输入有效的URL")

        logger.info(f"🌐 开始处理网页: {url}")

        # TODO: 实现实际的Web内容处理逻辑
        # 目前返回模拟响应，实际需要集成WebReader

        # 生成文档名（基于URL）
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        doc_name = f"web_{parsed_url.netloc}_{parsed_url.path.replace('/', '_')}"
        doc_name = doc_name.strip('_')

        logger.warning(f"⚠️ Web内容处理功能尚未完全实现，返回模拟响应")

        return {
            "status": "success",
            "message": f"网页内容处理完成: {url}",
            "doc_name": doc_name,
            "url": url,
            "save_outputs": request.save_outputs
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 处理网页内容失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理网页内容失败: {str(e)}")