"""
会话管理 API

提供会话列表、加载、删除等功能
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from ...services.chat_service import chat_service

router = APIRouter()


class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[dict]


class SessionResponse(BaseModel):
    """会话响应"""
    session_id: str
    mode: str
    doc_name: Optional[str]
    selected_docs: Optional[List[str]]
    title: str
    created_at: str
    updated_at: str
    message_count: int
    messages: Optional[List[dict]] = None


@router.get("/list/{mode}")
async def list_sessions(mode: str, limit: Optional[int] = None):
    """
    列出指定模式的会话列表

    Args:
        mode: 会话模式 (single/cross/manual)
        limit: 限制返回数量（可选）

    Returns:
        会话列表
    """
    try:
        if mode not in ["single", "cross", "manual"]:
            raise HTTPException(status_code=400, detail="无效的模式")

        sessions = chat_service.list_sessions(mode, limit)
        return {"sessions": sessions}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{mode}/{session_id}")
async def get_session(mode: str, session_id: str):
    """
    获取指定会话的完整信息（包含消息）

    Args:
        mode: 会话模式
        session_id: 会话ID（或 single 模式的 doc_name）

    Returns:
        完整的会话信息
    """
    try:
        if mode not in ["single", "cross", "manual"]:
            raise HTTPException(status_code=400, detail="无效的模式")

        session = chat_service.session_manager.load_session(session_id, mode)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        return session

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{mode}/{session_id}")
async def delete_session(mode: str, session_id: str):
    """
    删除指定会话

    Args:
        mode: 会话模式
        session_id: 会话ID

    Returns:
        删除结果
    """
    try:
        if mode not in ["single", "cross", "manual"]:
            raise HTTPException(status_code=400, detail="无效的模式")

        # SessionManager 会自动处理 single 模式的特殊情况
        # （通过 session_id 查找对应的 doc_name.json 文件）
        chat_service.delete_session(session_id, mode)
        return {"success": True, "message": "会话已删除"}

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current/info")
async def get_current_session():
    """
    获取当前会话信息

    Returns:
        当前会话信息，如果没有返回 null
    """
    try:
        current_session = chat_service.get_current_session()
        if not current_session:
            return None

        return current_session

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RenameRequest(BaseModel):
    """重命名请求"""
    new_title: str


@router.patch("/{mode}/{session_id}/rename")
async def rename_session(mode: str, session_id: str, request: RenameRequest):
    """
    重命名会话

    Args:
        mode: 会话模式
        session_id: 会话ID
        request: 重命名请求

    Returns:
        更新后的会话信息
    """
    try:
        if mode not in ["single", "cross", "manual"]:
            raise HTTPException(status_code=400, detail="无效的模式")

        if not request.new_title or len(request.new_title.strip()) == 0:
            raise HTTPException(status_code=400, detail="标题不能为空")

        # Load session
        session = chat_service.session_manager.load_session(session_id, mode)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        # Update title
        session["title"] = request.new_title.strip()

        # Save session
        from datetime import datetime
        session["updated_at"] = datetime.now().isoformat()

        from pathlib import Path
        session_dir = chat_service.session_manager._get_session_dir(mode)

        # For single mode, use doc_name as filename; for others, use session_id
        if mode == "single":
            filename = session.get("doc_name", session_id)
        else:
            filename = session_id

        session_path = session_dir / f"{filename}.json"
        chat_service.session_manager._save_session_file(session_path, session)

        return {
            "success": True,
            "session": session,
            "message": "会话已重命名"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
