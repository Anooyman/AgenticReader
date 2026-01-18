"""数据管理 API"""

from pathlib import Path
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from datetime import datetime

from ...config import get_logger
from ...services.data_service import DataService
from src.agents.indexing.doc_registry import DocumentRegistry

logger = get_logger(__name__)

router = APIRouter()
data_service = DataService()
doc_registry = DocumentRegistry()


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
    """列出所有已处理的文档

    优先使用 DocumentRegistry，以与 Indexing Agent 的文档管理保持一致；
    若注册表为空，则回退到文件系统扫描。
    """
    try:
        registry_docs = doc_registry.list_all()
        documents: List[Dict[str, Any]] = []

        def normalize_path(path_str: str) -> Path | None:
            """将注册表中的路径规范化为可用的本地路径"""
            if not path_str:
                return None
            cleaned = path_str.replace("\\", "/")
            return Path(cleaned)

        def first_match(paths: List[str], predicate) -> str:
            for p in paths:
                if predicate(p):
                    return p
            return ""

        if registry_docs:
            for doc in registry_docs:
                name = doc.get("doc_name")
                doc_id = doc.get("doc_id")
                generated = doc.get("generated_files", {})
                stage_files = []
                for stage in (doc.get("processing_stages") or {}).values():
                    stage_files.extend(stage.get("output_files") or [])

                # JSON 文件大小
                json_path = generated.get("json_data") or first_match(
                    stage_files, lambda f: "json_data" in f and f.endswith("data.json")
                )
                json_size = 0
                if json_path:
                    p = normalize_path(json_path)
                    if p.exists() and p.is_file():
                        json_size = p.stat().st_size

                # 向量库大小
                vector_path = generated.get("vector_db") or first_match(
                    stage_files, lambda f: "vector_db" in f
                )
                vector_size = data_service._get_dir_size(normalize_path(vector_path)) if vector_path else 0

                # 图片目录大小与数量
                images_list = generated.get("images") or []
                if not images_list:
                    alt_images = first_match(stage_files, lambda f: "pdf_image" in f)
                    images_list = [alt_images] if alt_images else []
                images_count = 0
                images_size = 0
                if images_list:
                    try:
                        img_dir = normalize_path(images_list[0])
                        if img_dir and img_dir.is_file():
                            img_dir = img_dir.parent
                        if img_dir and img_dir.exists():
                            images_count = len(list(img_dir.glob("*")))
                            images_size = data_service._get_dir_size(img_dir)
                    except Exception:
                        pass

                # 摘要文件大小
                summaries = generated.get("summaries") or []
                if not summaries:
                    summaries = [f for f in stage_files if f.endswith(".md") or "summary" in f]
                summary_size = 0
                for f in summaries:
                    p = normalize_path(f)
                    if p and p.exists() and p.is_file():
                        summary_size += p.stat().st_size

                documents.append({
                    "id": doc_id,
                    "name": name,
                    "modified_time": doc.get("indexed_at"),
                    "size": json_size + vector_size + images_size + summary_size,
                    "size_formatted": data_service._format_size(json_size + vector_size + images_size + summary_size),
                    "data_details": {
                        "json": {
                            "size": json_size,
                            "size_formatted": data_service._format_size(json_size)
                        },
                        "vector_db": {
                            "size": vector_size,
                            "size_formatted": data_service._format_size(vector_size)
                        },
                        "images": {
                            "size": images_size,
                            "size_formatted": data_service._format_size(images_size),
                            "count": images_count
                        },
                        "summary": {
                            "size": summary_size,
                            "size_formatted": data_service._format_size(summary_size),
                            "files": summaries
                        }
                    }
                })

            # 按修改时间排序
            documents.sort(key=lambda x: x.get("modified_time", ""), reverse=True)
            return {"success": True, "data": documents}

        # 回退：文件系统扫描
        fs_docs = await data_service.list_documents()
        return {"success": True, "data": fs_docs}
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


@router.delete("/data/registry/documents/{doc_id}")
async def delete_registry_document(doc_id: str, delete_source: bool = False) -> Dict[str, Any]:
    """根据注册表删除文档及其关联文件

    Args:
        doc_id: 文档ID（来自 DocumentRegistry）
        delete_source: 是否同时删除源文件
    """
    try:
        result = doc_registry.delete_all_files(doc_id, delete_source=delete_source)
        return {"success": result.get("success", False), "data": result}
    except Exception as e:
        logger.error(f"删除注册表文档失败: {e}")
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
