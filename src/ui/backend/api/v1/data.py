"""数据管理 API"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from datetime import datetime

from ...config import get_logger
from ...services.data_service import DataService

logger = get_logger(__name__)

router = APIRouter()
data_service = DataService()


@router.get("/data/overview")
async def get_data_overview() -> Dict[str, Any]:
    """获取数据存储概览"""
    try:
        overview = await data_service.get_storage_overview()
        return {
            "success": True,
            "data": overview
        }
    except Exception as e:
        logger.error(f"获取数据概览失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data/documents")
async def list_documents() -> Dict[str, Any]:
    """列出所有已处理的文档"""
    try:
        documents = await data_service.list_documents()
        return {
            "success": True,
            "data": documents
        }
    except Exception as e:
        logger.error(f"列出文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data/cache/{cache_type}")
async def get_cache_info(cache_type: str) -> Dict[str, Any]:
    """获取缓存信息

    Args:
        cache_type: 缓存类型 (pdf_image, vector_db, json_data)
    """
    try:
        cache_info = await data_service.get_cache_info(cache_type)
        return {
            "success": True,
            "data": cache_info
        }
    except Exception as e:
        logger.error(f"获取缓存信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/data/documents/{document_name}/parts")
async def delete_document_parts(
    document_name: str,
    data_types: List[str]
) -> Dict[str, Any]:
    """删除文档的特定数据部分

    Args:
        document_name: 文档名称
        data_types: 要删除的数据类型列表 (json, vector_db, images, summary, all)
    """
    try:
        result = await data_service.delete_document_data(document_name, data_types)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"删除文档部分数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/data/documents")
async def delete_documents(document_names: List[str]) -> Dict[str, Any]:
    """批量删除文档及其相关数据

    Args:
        document_names: 文档名称列表
    """
    try:
        result = await data_service.delete_documents(document_names)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"删除文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/data/cache/{cache_type}")
async def clear_cache(cache_type: str, items: List[str] = None) -> Dict[str, Any]:
    """清理缓存

    Args:
        cache_type: 缓存类型 (pdf_image, vector_db, json_data, all)
        items: 要删除的项目列表，None表示全部删除
    """
    try:
        result = await data_service.clear_cache(cache_type, items)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"清理缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/data/cleanup/smart")
async def smart_cleanup(days: int = 30) -> Dict[str, Any]:
    """智能清理超过指定天数的数据

    Args:
        days: 保留最近几天的数据，默认30天
    """
    try:
        result = await data_service.smart_cleanup(days)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"智能清理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/data/backup")
async def create_backup() -> Dict[str, Any]:
    """创建数据备份"""
    try:
        backup_file = await data_service.create_backup()
        return {
            "success": True,
            "data": {
                "backup_file": backup_file,
                "timestamp": datetime.now().isoformat()
            }
        }
    except Exception as e:
        logger.error(f"创建备份失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/data/reset")
async def full_reset(confirm: str) -> Dict[str, Any]:
    """完全重置所有数据

    Args:
        confirm: 必须是 "CONFIRM_RESET" 才能执行
    """
    if confirm != "CONFIRM_RESET":
        raise HTTPException(status_code=400, detail="需要确认码才能执行完全重置")

    try:
        result = await data_service.full_reset()
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        logger.error(f"完全重置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data/sessions/stats")
async def get_session_stats() -> Dict[str, Any]:
    """获取会话统计信息"""
    try:
        stats = await data_service.get_session_stats()
        return {
            "success": True,
            "data": stats
        }
    except Exception as e:
        logger.error(f"获取会话统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
