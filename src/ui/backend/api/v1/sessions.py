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


class MemoryScopeRequest(BaseModel):
    """会话记忆检索范围请求。

    namespaces=null 表示恢复默认（自库白名单）。字段带显式缺省 None：
    pydantic v2 下无默认值的 Optional 键仍属必填，省略整个键的"恢复默认"
    最常用写法（含 api.js 对 undefined 的序列化缺键）会撞 422。
    校验层同时接受缺省与显式 null，两者语义等价。
    """
    namespaces: Optional[List[str]] = None


@router.patch("/{session_id}/memory-scope")
async def set_memory_scope(session_id: str, request: MemoryScopeRequest):
    """
    设置会话级记忆检索范围（供 chat_service 透传给 Orchestrator）。

    校验集合 = gateway.DEFAULT_SEARCH_NAMESPACES（自库白名单）
             + NAMESPACE_AATF（DA 预留）+ gateway.EXTERNAL_SEARCH_NAMESPACES（占位）。
    null / 缺键 → 恢复默认；[] → 400（空作用域无意义）；含未知项 → 400；
    重复项在端点层保序去重后落库。
    注：AATF 目前随 DA 预留位放行，本地 _local_brief_load 实装前自库恒无
    AATF 行，选它检索结果为空——前端浮层已加同源提示，避免"加载了但搜
    不到"的断链错觉（blueprint OQ-1 口径）。
    """
    try:
        # 函数级延迟 import：api 层不往模块级拖记忆内核依赖链
        from src.memory import gateway

        allowed = (list(gateway.DEFAULT_SEARCH_NAMESPACES)
                   + [gateway.NAMESPACE_AATF]
                   + list(gateway.EXTERNAL_SEARCH_NAMESPACES))
        if request.namespaces is None:
            resolved = None
        else:
            if not request.namespaces:
                raise HTTPException(status_code=400, detail="namespaces 不能为空")
            resolved = []
            for n in request.namespaces:
                n = str(n).strip()
                if n not in allowed:
                    raise HTTPException(
                        status_code=400,
                        detail=f"未知的 namespace: {n!r}；允许值: {', '.join(allowed)}")
                if n not in resolved:
                    resolved.append(n)

        session = chat_service.session_manager.set_session_memory_namespaces(
            session_id, resolved)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        return {
            "success": True,
            "session": session,
            "message": "记忆检索范围已更新",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
