"""Chat相关API端点"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Tuple

from ...config import get_logger
from ...services.chat_service import chat_service

router = APIRouter(prefix="/chat", tags=["Chat"])
logger = get_logger(__name__)


@router.get("/history")
async def get_chat_history():
    """获取聊天历史"""
    try:
        # 目前返回空历史，因为POC UI主要依赖WebSocket进行聊天
        # 实际的聊天历史存储在客户端localStorage中
        return {
            "status": "success",
            "history": []
        }
    except Exception as e:
        logger.error(f"❌ 获取聊天历史失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取聊天历史失败: {str(e)}")


@router.post("/clear")
async def clear_chat():
    """清除聊天历史"""
    try:
        # 重置聊天服务状态
        chat_service.reset()
        logger.info("🗑️ 聊天历史已清除")

        return {
            "status": "success",
            "message": "聊天历史已清除"
        }
    except Exception as e:
        logger.error(f"❌ 清除聊天历史失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除聊天历史失败: {str(e)}")