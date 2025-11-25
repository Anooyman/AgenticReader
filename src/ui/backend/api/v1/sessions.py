"""会话管理API路由"""

import tempfile
import os
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import FileResponse

from ...services.session_service import SessionService
from ...models.session import (
    SessionListResponse,
    SessionExportRequest,
    SessionImportRequest
)
from ...config.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()

# 依赖注入
def get_session_service() -> SessionService:
    """获取会话服务实例"""
    return SessionService()


@router.post("/sessions/save")
async def save_sessions(
    session_service: SessionService = Depends(get_session_service)
):
    """手动保存当前会话"""
    try:
        success = session_service.save_sessions(create_backup=True)
        if success:
            return {"status": "success", "message": "会话已保存"}
        else:
            raise HTTPException(status_code=500, detail="保存会话失败")
    except Exception as e:
        logger.error(f"保存会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存会话失败: {str(e)}")


@router.post("/sessions/add")
async def save_single_session(
    session_data: Dict[str, Any],
    session_service: SessionService = Depends(get_session_service)
):
    """保存单个会话数据"""
    try:
        # 提取会话信息
        chat_id = session_data.get('chatId')
        doc_name = session_data.get('docName')
        messages = session_data.get('messages', [])
        timestamp = session_data.get('timestamp')
        has_pdf_reader = session_data.get('hasPdfReader', False)
        has_web_reader = session_data.get('hasWebReader', False)
        provider = session_data.get('provider', 'openai')

        if not chat_id or not doc_name:
            raise HTTPException(status_code=400, detail="缺少必要的会话信息")

        # 创建会话数据模型
        from ...models.session import ChatMessage

        # 转换消息格式
        converted_messages = []
        for msg in messages:
            if isinstance(msg, list) and len(msg) >= 3:
                converted_messages.append(ChatMessage(
                    role=msg[0],
                    content=msg[1],
                    timestamp=msg[2]
                ))

        # 创建会话模型并添加到缓存
        from ...models.session import SessionModel
        from datetime import datetime

        session = SessionModel(
            chat_id=chat_id,
            doc_name=doc_name,
            has_pdf_reader=has_pdf_reader,
            has_web_reader=has_web_reader,
            provider=provider,
            messages=converted_messages,
            timestamp=timestamp,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        # 检查是否已存在相同的会话，如果存在则只更新，不创建新备份
        existing_session = session_service._sessions_cache.get(chat_id)
        is_new_session = existing_session is None

        # 添加到缓存
        session_service._sessions_cache[chat_id] = session

        # 🔥 优化备份策略：只有新会话或消息数量显著增加时才创建备份
        should_create_backup = is_new_session
        if not is_new_session and existing_session:
            # 如果消息数量增加了5条或更多，才创建备份
            existing_message_count = len(existing_session.messages) if existing_session.messages else 0
            current_message_count = len(converted_messages)
            should_create_backup = (current_message_count - existing_message_count) >= 5

        success = session_service.save_sessions(create_backup=should_create_backup)

        if success:
            backup_info = "创建备份" if should_create_backup else "仅更新"
            logger.info(f"会话已保存: {chat_id}, 文档: {doc_name}, 消息数: {len(messages)}, 操作: {backup_info}")
            return {"status": "success", "message": f"会话已保存: {chat_id} ({backup_info})"}
        else:
            raise HTTPException(status_code=500, detail="保存会话到文件失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存单个会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存会话失败: {str(e)}")


@router.get("/sessions/list", response_model=SessionListResponse)
async def list_sessions(
    session_service: SessionService = Depends(get_session_service)
):
    """获取所有会话列表"""
    try:
        sessions = session_service.get_all_sessions()
        return SessionListResponse(
            sessions=sessions,
            count=len(sessions)
        )
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(e)}")


@router.post("/sessions/export")
async def export_sessions(
    request: SessionExportRequest,
    session_service: SessionService = Depends(get_session_service)
):
    """导出会话数据"""
    try:
        export_path = session_service.export_sessions(request.filename)

        return {
            "status": "success",
            "message": "会话导出成功",
            "export_path": export_path,
            "filename": os.path.basename(export_path)
        }
    except Exception as e:
        logger.error(f"导出会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"导出会话失败: {str(e)}")


@router.post("/sessions/import")
async def import_sessions(
    request: SessionImportRequest,
    file: UploadFile = File(...),
    session_service: SessionService = Depends(get_session_service)
):
    """导入会话数据"""
    try:
        # 检查文件类型
        if not file.filename.lower().endswith('.json'):
            raise HTTPException(status_code=400, detail="只支持JSON文件")

        # 保存上传的文件到临时位置
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.json') as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name

        try:
            # 导入会话数据
            success = session_service.import_sessions(tmp_path, merge=request.merge)

            if success:
                # 保存到文件
                session_service.save_sessions(create_backup=True)

                return {
                    "status": "success",
                    "message": f"会话导入成功({'合并' if request.merge else '替换'}模式)",
                    "merge": request.merge
                }
            else:
                raise HTTPException(status_code=400, detail="导入文件格式无效")

        finally:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except:
                pass

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导入会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入会话失败: {str(e)}")


@router.get("/sessions/export/{filename}")
async def download_export(
    filename: str,
    session_service: SessionService = Depends(get_session_service)
):
    """下载导出的会话文件"""
    export_path = session_service.exports_dir / filename

    if not export_path.exists():
        raise HTTPException(status_code=404, detail="导出文件不存在")

    return FileResponse(
        str(export_path),
        media_type='application/json',
        filename=filename
    )


@router.delete("/sessions/clear")
async def clear_all_sessions(
    session_service: SessionService = Depends(get_session_service)
):
    """清空所有会话"""
    try:
        success = session_service.clear_all_sessions()

        if success:
            # 保存到文件
            session_service.save_sessions(create_backup=True)
            return {"status": "success", "message": "所有会话已清空"}
        else:
            raise HTTPException(status_code=500, detail="清空会话失败")

    except Exception as e:
        logger.error(f"清空会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"清空会话失败: {str(e)}")


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    session_service: SessionService = Depends(get_session_service)
):
    """删除指定会话"""
    try:
        # 检查会话是否存在
        if session_id not in session_service._sessions_cache:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        # 记录被删除会话的信息用于日志
        deleted_session = session_service._sessions_cache.get(session_id)
        
        # 从内存中删除会话
        success = session_service.delete_session(session_id)

        if success:
            # 🔥 关键：删除会话后立即保存到文件，确保JSON也被更新
            session_service.save_sessions(create_backup=False)
            
            if deleted_session:
                logger.info(f"成功删除会话 {session_id}: {deleted_session.doc_name}")
            
            return {
                "status": "success", 
                "message": "会话已删除",
                "deleted_session_id": session_id
            }
        else:
            raise HTTPException(status_code=500, detail="删除会话失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除会话失败: {str(e)}")


@router.post("/sessions/cleanup")
async def cleanup_meaningless_sessions(
    session_service: SessionService = Depends(get_session_service)
):
    """清理无意义的会话"""
    try:
        cleaned_count = session_service.cleanup_meaningless_sessions()

        if cleaned_count > 0:
            # 保存清理后的数据
            session_service.save_sessions(create_backup=False)

        return {
            "status": "success",
            "message": f"清理了 {cleaned_count} 个无意义会话",
            "cleaned_count": cleaned_count
        }

    except Exception as e:
        logger.error(f"清理会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"清理会话失败: {str(e)}")