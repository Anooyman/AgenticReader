"""聊天 API"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()


class ChatInitRequest(BaseModel):
    """聊天初始化请求"""
    enabled_tools: Optional[List[str]] = None  # ["retrieve_documents", "search_web"]
    selected_docs: Optional[List[str]] = None  # ["paper_a.pdf", "paper_b.pdf"]
    session_id: Optional[str] = None  # 可选：加载指定会话


@router.post("/initialize")
async def initialize_chat(request: ChatInitRequest):
    """
    初始化聊天服务

    Args:
        request: 初始化请求，包含工具/文档选择和可选的会话ID
    """
    try:
        from ...services.chat_service import chat_service

        result = chat_service.initialize(
            enabled_tools=request.enabled_tools,
            selected_docs=request.selected_docs,
            session_id=request.session_id,
        )

        if result.get("success"):
            return {
                "status": "success",
                "message": "聊天服务初始化成功",
                "session_id": result.get("session_id"),
                "enabled_tools": result.get("enabled_tools"),
                "selected_docs": result.get("selected_docs"),
                "title": result.get("title"),
                "message_count": result.get("message_count"),
                "messages": result.get("messages", []),
                "has_more_messages": result.get("has_more_messages", False)
            }
        else:
            error_msg = result.get("error", "聊天服务初始化失败")
            raise HTTPException(status_code=400, detail=error_msg)

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 初始化聊天服务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear")
async def clear_chat():
    """清空聊天历史"""
    try:
        from ...services.chat_service import chat_service
        chat_service.reset()

        return {
            "status": "success",
            "message": "聊天历史已清空"
        }

    except Exception as e:
        print(f"❌ 清空聊天历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/load-more-messages")
async def load_more_messages(offset: int = 0, limit: int = 20):
    """
    加载更多历史消息（用于分页加载）

    Args:
        offset: 偏移量（已加载的消息数）
        limit: 每次加载的消息数（默认20）

    Returns:
        {
            "messages": [...],
            "total": int,
            "has_more": bool
        }
    """
    try:
        from ...services.chat_service import chat_service

        result = chat_service.load_more_messages(offset=offset, limit=limit)

        return {
            "status": "success",
            "messages": result.get("messages", []),
            "total": result.get("total", 0),
            "has_more": result.get("has_more", False)
        }

    except Exception as e:
        print(f"❌ 加载更多消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
