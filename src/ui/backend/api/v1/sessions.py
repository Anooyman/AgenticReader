"""
会话管理 API

提供会话列表、加载、删除等功能
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from ...services.chat_service import chat_service

router = APIRouter()


@router.get("/list")
async def list_sessions(limit: Optional[int] = None):
    """
    列出所有会话

    Args:
        limit: 限制返回数量（可选）
    """
    try:
        sessions = chat_service.list_sessions(limit)
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current/info")
async def get_current_session():
    """获取当前会话信息"""
    try:
        current_session = chat_service.get_current_session()
        if not current_session:
            return None
        return current_session
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}")
async def get_session(session_id: str):
    """
    获取指定会话的完整信息（包含消息）

    Args:
        session_id: 会话ID
    """
    try:
        session = chat_service.session_manager.load_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        return session
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """
    删除指定会话

    Args:
        session_id: 会话ID
    """
    try:
        chat_service.delete_session(session_id)
        return {"success": True, "message": "会话已删除"}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RenameRequest(BaseModel):
    """重命名请求"""
    new_title: str


@router.patch("/{session_id}/rename")
async def rename_session(session_id: str, request: RenameRequest):
    """
    重命名会话

    Args:
        session_id: 会话ID
        request: 重命名请求
    """
    try:
        if not request.new_title or len(request.new_title.strip()) == 0:
            raise HTTPException(status_code=400, detail="标题不能为空")

        session = chat_service.session_manager.rename_session(
            session_id, request.new_title.strip()
        )

        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        return {
            "success": True,
            "session": session,
            "message": "会话已重命名"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
