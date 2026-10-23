"""数据管理 API——存储管理域（REFACTOR_REPORT P2-4 拆分产物）

本模块负责 /data 页的"存储"类端点：存储概览（/overview）、待索引 PDF
清单（/documents/pending）与源文件清理（DELETE /pdfs）、会话统计
（/sessions/stats）、智能清理（/cleanup/smart）。

文档产物清单/摘要/删除在 ``data.py``（documents 域）；任务类在
``data_ops.py``。URL 前缀 ``/api/v1/data`` 由 app.py 的 include_router
统一提供，本模块路由路径与拆分前逐条一致。
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
from datetime import datetime, timedelta

from ...config import (
    PDF_DIR, JSON_DATA_DIR, VECTOR_DB_DIR,
    PDF_IMAGE_DIR, OUTPUT_DIR, DATA_DIR
)
from src.core.document_management import DocumentRegistry
from src.utils.path_guard import safe_path
# 智能清理复用 documents 域的删除端点（同一 parts 映射与响应体翻译），
# 方向单向：storage → documents，documents 不 import 本模块，无循环。
from .data import DeletePartsRequest, delete_document_parts
from .data_common import get_dir_size

router = APIRouter()


# ==================== Pydantic Models ====================

class StorageOverview(BaseModel):
    """存储概览"""
    total_documents: int
    total_sessions: int
    total_storage_mb: float
    last_cleanup: Optional[str] = None
    breakdown: Dict[str, Dict[str, Any]]


class SessionStats(BaseModel):
    """会话统计信息"""
    total_sessions: int
    by_mode: Dict[str, int]
    total_messages: int
    last_activity: Optional[str] = None


class PendingPDFDeleteRequest(BaseModel):
    """删除未索引 PDF 源文件的请求"""
    filenames: List[str]


class PendingPDF(BaseModel):
    """待索引PDF信息"""
    filename: str
    file_path: str
    size_mb: float
    created_at: str


# ==================== Helper Functions ====================

def count_sessions() -> Dict[str, Any]:
    """
    统计会话信息（扫描平级目录）

    Returns:
        会话统计字典
    """
    sessions_dir = DATA_DIR / "sessions"

    if not sessions_dir.exists():
        return {
            "total": 0,
            "by_mode": {"single": 0, "cross": 0, "manual": 0},
            "total_messages": 0,
            "last_activity": None
        }

    stats = {
        "total": 0,
        "by_mode": {"single": 0, "cross": 0, "manual": 0},
        "total_messages": 0,
        "last_activity": None
    }

    last_update = None

    for session_file in sessions_dir.glob("*.json"):
        if session_file.name == "metadata.json":
            continue
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
                stats["total"] += 1

                # 按 mode 字段统计
                mode = session_data.get("mode", "cross")
                if mode in stats["by_mode"]:
                    stats["by_mode"][mode] += 1

                messages = session_data.get("messages", [])
                stats["total_messages"] += len(messages)

                updated_at = session_data.get("updated_at")
                if updated_at:
                    if last_update is None or updated_at > last_update:
                        last_update = updated_at
        except Exception:
            continue

    stats["last_activity"] = last_update
    return stats


# ==================== API Endpoints ====================

@router.get("/overview", response_model=StorageOverview)
async def get_storage_overview():
    """
    获取存储概览

    Returns:
        存储概览信息
    """
    try:
        registry = DocumentRegistry()
        doc_count = registry.count()

        session_stats = count_sessions()

        # Calculate storage breakdown
        breakdown = {
            "documents": {
                "count": doc_count,
                "size_mb": get_dir_size(PDF_DIR)
            },
            "json_data": {
                "size_mb": get_dir_size(JSON_DATA_DIR)
            },
            "vector_db": {
                "size_mb": get_dir_size(VECTOR_DB_DIR)
            },
            "images": {
                "size_mb": get_dir_size(PDF_IMAGE_DIR)
            },
            "summaries": {
                "size_mb": get_dir_size(OUTPUT_DIR)
            },
            "sessions": {
                "count": session_stats["total"],
                "size_mb": get_dir_size(DATA_DIR / "sessions")
            }
        }

        total_storage = sum(
            item.get("size_mb", 0) for item in breakdown.values()
        )

        return StorageOverview(
            total_documents=doc_count,
            total_sessions=session_stats["total"],
            total_storage_mb=total_storage,
            last_cleanup=None,  # TODO: Track cleanup history
            breakdown=breakdown
        )

    except Exception as e:
        print(f"❌ 获取存储概览失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/pending", response_model=List[PendingPDF])
async def get_pending_pdfs():
    """
    获取待索引的PDF文件列表

    Returns:
        待索引PDF列表
    """
    try:
        registry = DocumentRegistry()
        indexed_pdfs = set()

        # 获取所有已索引的PDF文件名
        all_docs = registry.list_all()
        for doc in all_docs:
            doc_name = doc.get("doc_name", "")
            # 确保添加.pdf扩展名
            if not doc_name.endswith('.pdf'):
                doc_name += '.pdf'
            indexed_pdfs.add(doc_name)

        # 扫描PDF目录
        pending_pdfs = []
        if PDF_DIR.exists():
            for pdf_file in PDF_DIR.glob("*.pdf"):
                if pdf_file.name not in indexed_pdfs:
                    # 未索引的PDF
                    stat = pdf_file.stat()
                    pending_pdfs.append(PendingPDF(
                        filename=pdf_file.name,
                        file_path=str(pdf_file),
                        size_mb=stat.st_size / (1024 * 1024),
                        created_at=datetime.fromtimestamp(stat.st_ctime).isoformat()
                    ))

        # 按创建时间排序（最新的在前）
        pending_pdfs.sort(key=lambda x: x.created_at, reverse=True)

        return pending_pdfs

    except Exception as e:
        print(f"❌ 获取待索引PDF列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/pdfs")
async def delete_pdf_source_files(request: PendingPDFDeleteRequest):
    """
    直接删除 data/pdf/ 下的 PDF 源文件（用于清理未索引或遗留的文件）

    出于安全考虑：
    - 只接受 data/pdf/ 目录内的文件名（禁止路径穿越）
    - 仍被索引的文档不会在此删除，需通过文档的"完全删除"处理

    Args:
        request: 要删除的文件名列表

    Returns:
        删除结果
    """
    if not request.filenames:
        raise HTTPException(status_code=400, detail="未指定要删除的文件")

    try:
        registry = DocumentRegistry()
        indexed_names = set()
        for doc in registry.list_all():
            name = doc.get("doc_name", "")
            indexed_names.add(name if name.endswith(".pdf") else f"{name}.pdf")

        pdf_root = PDF_DIR.resolve()
        deleted_items = []
        failed_items = []
        freed_space_mb = 0.0

        for filename in request.filenames:
            raw = str(filename).strip()

            # 禁止目录穿越 / 子路径
            if not raw or '/' in raw or '\\' in raw or raw.startswith('.'):
                failed_items.append(f"{filename}: 非法文件名")
                continue

            candidate = raw if raw.lower().endswith(".pdf") else f"{raw}.pdf"

            # 路径拼装统一过 path_guard 的唯一实现（与上面的手工检查同语义，
            # 收敛后删除类路径不再各写一套校验）
            try:
                safe_path(PDF_DIR, candidate)
            except ValueError as guard_e:
                failed_items.append(f"{candidate}: 非法文件名")
                continue

            file_path = PDF_DIR / candidate

            try:
                if not file_path.is_file():
                    failed_items.append(f"{candidate}: 文件不存在")
                    continue
                if pdf_root not in file_path.resolve().parents:
                    failed_items.append(f"{candidate}: 不在 PDF 目录内")
                    continue
            except OSError as e:
                failed_items.append(f"{candidate}: {e}")
                continue

            if candidate in indexed_names:
                failed_items.append(f"{candidate}: 文档仍处于索引状态，请使用文档的“完全删除”")
                continue

            try:
                size = file_path.stat().st_size / (1024 * 1024)
                file_path.unlink()
                deleted_items.append(f"{candidate} ({size:.2f} MB)")
                freed_space_mb += size
                print(f"✓ 已删除 PDF 源文件: {file_path}")
            except Exception as e:
                failed_items.append(f"{candidate}: {e}")

        return {
            "status": "success" if not failed_items else "partial",
            "deleted": deleted_items,
            "failed": failed_items,
            "count": len(deleted_items),
            "freed_mb": round(freed_space_mb, 2)
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 删除 PDF 源文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/stats", response_model=SessionStats)
async def get_session_stats():
    """
    获取会话统计信息

    Returns:
        会话统计
    """
    try:
        stats = count_sessions()

        return SessionStats(
            total_sessions=stats["total"],
            by_mode=stats["by_mode"],
            total_messages=stats["total_messages"],
            last_activity=stats["last_activity"]
        )

    except Exception as e:
        print(f"❌ 获取会话统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup/smart")
async def smart_cleanup(days: int = Query(default=30, ge=1, le=365)):
    """
    智能清理旧数据

    Args:
        days: 清理多少天前的数据（默认30天）

    Returns:
        清理结果
    """
    try:
        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff_date.isoformat()

        registry = DocumentRegistry()
        all_docs = registry.list_all()

        deleted_docs = []
        freed_space_mb = 0.0

        for doc in all_docs:
            indexed_at = doc.get("indexed_at", doc.get("created_at", ""))

            if indexed_at and indexed_at < cutoff_str:
                doc_name = doc.get("doc_name", "")

                # Delete this document
                try:
                    result = await delete_document_parts(
                        doc_name,
                        DeletePartsRequest(parts=["all"])
                    )

                    deleted_docs.append(doc_name)
                    freed_space_mb += result["freed_space_mb"]

                except Exception as e:
                    print(f"⚠️  清理文档 {doc_name} 失败: {e}")

        return {
            "status": "success",
            "cutoff_date": cutoff_str,
            "deleted_documents": deleted_docs,
            "count": len(deleted_docs),
            "freed_mb": round(freed_space_mb, 2)
        }

    except Exception as e:
        print(f"❌ 智能清理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
