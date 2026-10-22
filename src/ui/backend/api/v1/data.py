"""数据管理 API

提供文档数据、会话数据和存储管理功能
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from pathlib import Path
import shutil
import json
from datetime import datetime, timedelta

from ...config import (
    PDF_DIR, JSON_DATA_DIR, VECTOR_DB_DIR,
    PDF_IMAGE_DIR, OUTPUT_DIR, DATA_DIR
)
from src.core.document_management import DocumentRegistry
from src.utils.path_guard import safe_path
from ...services.task_service import task_manager

router = APIRouter()


# ==================== Pydantic Models ====================

class StorageOverview(BaseModel):
    """存储概览"""
    total_documents: int
    total_sessions: int
    total_storage_mb: float
    last_cleanup: Optional[str] = None
    breakdown: Dict[str, Dict[str, Any]]


class DocumentDetail(BaseModel):
    """文档详细信息（含元数据）"""
    doc_id: str
    doc_name: str
    doc_type: str

    # 从 metadata_enhanced 中提取的字段
    title: Optional[str] = None
    abstract: Optional[str] = None
    keywords: Optional[List[str]] = None
    topics: Optional[List[str]] = None
    extended_summary: Optional[str] = None

    # 数据大小信息
    json_size_mb: float = 0.0
    vector_db_size_mb: float = 0.0
    images_size_mb: float = 0.0
    summary_size_mb: float = 0.0
    pdf_size_mb: float = 0.0
    total_size_mb: float = 0.0

    # 文件存在状态
    has_json: bool = False
    has_vector_db: bool = False
    has_images: bool = False
    has_summary: bool = False
    has_pdf: bool = False

    # 时间信息
    created_at: str
    indexed_at: Optional[str] = None


class SessionStats(BaseModel):
    """会话统计信息"""
    total_sessions: int
    by_mode: Dict[str, int]
    total_messages: int
    last_activity: Optional[str] = None


class DeletePartsRequest(BaseModel):
    """删除部分数据的请求"""
    parts: List[str]  # ["json", "vector_db", "images", "summary", "pdf", "all"]


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""
    doc_names: List[str]
    delete_source: bool = False  # 是否同时删除本地源 PDF 文件


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

def get_dir_size(path: Path) -> float:
    """
    计算目录大小（MB）

    Args:
        path: 目录路径

    Returns:
        目录大小（MB）
    """
    if not path.exists():
        return 0.0

    total_size = 0
    if path.is_file():
        total_size = path.stat().st_size
    elif path.is_dir():
        for item in path.rglob('*'):
            if item.is_file():
                try:
                    total_size += item.stat().st_size
                except (OSError, PermissionError):
                    continue

    return total_size / (1024 * 1024)  # Convert to MB


def get_source_pdf_path(doc_name_base: str, doc_info: Optional[Dict] = None) -> Optional[Path]:
    """
    定位文档的本地源 PDF 文件

    优先使用 data/pdf/{name}.pdf（上传/索引时使用的目录），
    其次回退到注册表里记录的 doc_path（可能是外部路径）。

    Args:
        doc_name_base: 文档名称（不含 .pdf 扩展名）
        doc_info: 注册表中的文档信息（可选）

    Returns:
        存在的源文件路径，找不到则返回 None
    """
    candidates = []
    if PDF_DIR.exists():
        candidates.append(PDF_DIR / f"{doc_name_base}.pdf")
    if doc_info:
        doc_path = doc_info.get("doc_path")
        if doc_path:
            candidates.append(Path(doc_path))

    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue

    return None


def get_document_data_sizes(doc_name: str, doc_info: Dict) -> Dict[str, float]:
    """
    获取文档各部分数据大小

    Args:
        doc_name: 文档名称
        doc_info: 文档信息字典

    Returns:
        各部分大小字典（MB）
    """
    # Strip .pdf extension once at the beginning for all path lookups
    doc_name_base = doc_name.replace('.pdf', '') if doc_name.endswith('.pdf') else doc_name

    sizes = {
        "json_size_mb": 0.0,
        "vector_db_size_mb": 0.0,
        "images_size_mb": 0.0,
        "summary_size_mb": 0.0,
        "pdf_size_mb": 0.0,
        "has_json": False,
        "has_vector_db": False,
        "has_images": False,
        "has_summary": False,
        "has_pdf": False
    }

    # JSON data (in json_data/{doc_name_base}/ directory)
    json_dir = JSON_DATA_DIR / doc_name_base
    if json_dir.exists():
        sizes["json_size_mb"] = get_dir_size(json_dir)
        sizes["has_json"] = True

    # Vector DB (in vector_db/{doc_name_base}_data_index/ directory)
    vector_db_path = VECTOR_DB_DIR / f"{doc_name_base}_data_index"
    if vector_db_path.exists():
        sizes["vector_db_size_mb"] = get_dir_size(vector_db_path)
        sizes["has_vector_db"] = True

    # Images (in pdf_image/{doc_name_base}/ directory)
    images_dir = PDF_IMAGE_DIR / doc_name_base
    if images_dir.exists():
        sizes["images_size_mb"] = get_dir_size(images_dir)
        sizes["has_images"] = True

    # Summary files (MD and PDF in output directory)
    # Summary files are named as {doc_name_base}_brief_summary.md or {doc_name_base}_summary.md
    for suffix in ['_brief_summary', '_summary', '']:
        for ext in ['.md', '.pdf']:
            summary_file = OUTPUT_DIR / f"{doc_name_base}{suffix}{ext}"
            if summary_file.exists():
                sizes["summary_size_mb"] += get_dir_size(summary_file)
                sizes["has_summary"] = True

    # Source PDF file (in pdf/ directory or registered doc_path)
    source_pdf = get_source_pdf_path(doc_name_base, doc_info)
    if source_pdf is not None:
        sizes["pdf_size_mb"] = get_dir_size(source_pdf)
        sizes["has_pdf"] = True

    return sizes


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


@router.get("/documents", response_model=List[DocumentDetail])
async def get_documents_detailed():
    """
    获取文档详细列表（包含元数据和大小信息）

    Returns:
        文档详细信息列表
    """
    try:
        registry = DocumentRegistry()
        all_docs = registry.list_all(sort_by="indexed_at")

        detailed_docs = []

        for doc in all_docs:
            doc_name = doc.get("doc_name", "")

            # 获取 metadata_enhanced
            metadata_enhanced = doc.get("metadata_enhanced", {})

            # 获取数据大小
            sizes = get_document_data_sizes(doc_name, doc)

            # 构建详细信息
            detail = DocumentDetail(
                doc_id=doc.get("doc_id", ""),
                doc_name=doc_name,
                doc_type=doc.get("doc_type", "pdf"),

                # 元数据
                title=metadata_enhanced.get("title"),
                abstract=metadata_enhanced.get("abstract"),
                keywords=metadata_enhanced.get("keywords", []),
                topics=metadata_enhanced.get("topics", []),
                extended_summary=metadata_enhanced.get("extended_summary"),

                # 大小信息
                json_size_mb=sizes["json_size_mb"],
                vector_db_size_mb=sizes["vector_db_size_mb"],
                images_size_mb=sizes["images_size_mb"],
                summary_size_mb=sizes["summary_size_mb"],
                pdf_size_mb=sizes["pdf_size_mb"],
                total_size_mb=(
                    sizes["json_size_mb"] +
                    sizes["vector_db_size_mb"] +
                    sizes["images_size_mb"] +
                    sizes["summary_size_mb"]
                ),

                # 存在状态
                has_json=sizes["has_json"],
                has_vector_db=sizes["has_vector_db"],
                has_images=sizes["has_images"],
                has_summary=sizes["has_summary"],
                has_pdf=sizes["has_pdf"],

                # 时间信息
                created_at=doc.get("created_at", ""),
                indexed_at=doc.get("indexed_at")
            )

            detailed_docs.append(detail)

        return detailed_docs

    except Exception as e:
        print(f"❌ 获取文档列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{doc_name}/summary")
async def get_document_summary(doc_name: str):
    """
    获取文档的brief_summary

    Args:
        doc_name: 文档名称

    Returns:
        包含brief_summary的字典
    """
    try:
        registry = DocumentRegistry()
        doc = registry.get_by_name(doc_name)

        if not doc:
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_name}")

        brief_summary = doc.get("brief_summary", "暂无摘要信息")

        return {
            "doc_name": doc_name,
            "brief_summary": brief_summary
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 获取文档摘要失败: {e}")
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


async def _index_pdf_background(task_id: str, filename: str, pdf_path: Path):
    """
    后台索引任务

    Args:
        task_id: 任务ID
        filename: PDF文件名
        pdf_path: PDF文件路径
    """
    try:
        from src.agents.indexing import IndexingAgent
        from .config import load_config

        doc_name_base = filename.replace('.pdf', '') if filename.endswith('.pdf') else filename

        # 更新任务进度
        task_manager.update_task(task_id, progress=10, status="running")

        # 从配置加载 provider 和 pdf_preset
        config = load_config()
        provider = config.get("provider", "openai")
        pdf_preset = config.get("pdf_preset", "high")
        print(f"📌 使用配置: provider={provider}, pdf_preset={pdf_preset}")

        # 创建索引agent
        indexing_agent = IndexingAgent(provider=provider, pdf_preset=pdf_preset)
        task_manager.update_task(task_id, progress=20)

        print(f"🔄 后台索引任务开始: {filename} (task_id: {task_id})")

        # 执行索引
        result = await indexing_agent.graph.ainvoke({
            "doc_name": doc_name_base,
            "doc_path": str(pdf_path),
            "doc_type": "pdf",
            "is_complete": False,
            "status": "pending"
        })

        task_manager.update_task(task_id, progress=90)

        if result.get("is_complete"):
            task_manager.complete_task(task_id, success=True)
            print(f"✅ 后台索引任务完成: {filename}")
        else:
            error_msg = result.get("error", "未知错误")
            task_manager.complete_task(task_id, success=False, error=error_msg)
            print(f"❌ 后台索引任务失败: {filename}, 错误: {error_msg}")

    except Exception as e:
        error_msg = str(e)
        task_manager.complete_task(task_id, success=False, error=error_msg)
        print(f"❌ 后台索引任务异常: {filename}, 错误: {error_msg}")
        import traceback
        traceback.print_exc()


@router.post("/documents/{filename}/index")
async def index_pdf(filename: str, background_tasks: BackgroundTasks):
    """
    启动PDF索引后台任务

    Args:
        filename: PDF文件名
        background_tasks: FastAPI后台任务

    Returns:
        任务信息
    """
    try:
        # 检查PDF文件是否存在
        pdf_path = PDF_DIR / filename
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail=f"PDF文件不存在: {filename}")

        # 检查是否已经索引
        registry = DocumentRegistry()
        doc_name_base = filename.replace('.pdf', '') if filename.endswith('.pdf') else filename
        if registry.get_by_name(doc_name_base):
            raise HTTPException(status_code=400, detail=f"文档已索引: {filename}")

        # 创建后台任务
        task_id = task_manager.create_task(
            task_type="pdf_index",
            filename=filename,
            doc_name=doc_name_base
        )

        # 添加后台任务
        background_tasks.add_task(_index_pdf_background, task_id, filename, pdf_path)

        print(f"📋 索引任务已创建: {filename} (task_id: {task_id})")

        return {
            "status": "started",
            "task_id": task_id,
            "filename": filename,
            "message": f"索引任务已启动"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 创建索引任务失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """
    查询任务状态

    Args:
        task_id: 任务ID

    Returns:
        任务状态信息
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/tasks")
async def get_all_tasks():
    """
    获取所有任务（运行中 + 最近完成）

    Returns:
        任务列表
    """
    running = task_manager.get_running_tasks()
    completed = task_manager.get_recent_completed_tasks(limit=20)

    return {
        "running": running,
        "recent_completed": completed,
        "total_running": len(running)
    }


@router.delete("/documents/{doc_name}/parts")
async def delete_document_parts(doc_name: str, request: DeletePartsRequest):
    """
    删除文档的指定部分数据（粒度控制）

    Args:
        doc_name: 文档名称
        request: 删除请求（包含要删除的部分）

    Returns:
        删除结果
    """
    try:
        registry = DocumentRegistry()
        doc_info = registry.get_by_name(doc_name)

        # 目录穿越防护：doc_name 会派生出多个数据目录路径，
        # 统一校验名称不越过 DATA_DIR，杜绝通过 "../" 等操作删除数据目录外的内容
        try:
            safe_path(DATA_DIR, doc_name)
        except ValueError as guard_e:
            raise HTTPException(status_code=400, detail=f"非法文档名: {guard_e}")

        # 注意：即使Registry中没有记录，也继续尝试删除文件
        # 这样可以清理孤立的文件（Registry已被删除但文件还在的情况）

        # Strip .pdf extension for correct path lookups
        doc_name_base = doc_name.replace('.pdf', '') if doc_name.endswith('.pdf') else doc_name

        deleted_items = []
        failed_items = []
        freed_space_mb = 0.0

        parts = request.parts

        # 如果包含 "all"，则删除所有派生数据
        # 注意："all" 不包含本地源 PDF 文件，需显式指定 "pdf"
        if "all" in parts:
            parts = ["json", "vector_db", "images", "summary", "registry"] + (
                ["pdf"] if "pdf" in parts else []
            )

        # 删除 JSON 数据
        if "json" in parts:
            json_dir = JSON_DATA_DIR / doc_name_base
            if json_dir.exists():
                try:
                    size = get_dir_size(json_dir)
                    shutil.rmtree(json_dir)
                    deleted_items.append(f"JSON 数据 ({size:.2f} MB)")
                    freed_space_mb += size
                except Exception as e:
                    failed_items.append(f"JSON 数据: {e}")

        # 删除向量数据库
        if "vector_db" in parts:
            vector_db_path = VECTOR_DB_DIR / f"{doc_name_base}_data_index"
            if vector_db_path.exists():
                try:
                    size = get_dir_size(vector_db_path)
                    shutil.rmtree(vector_db_path)
                    deleted_items.append(f"向量数据库 ({size:.2f} MB)")
                    freed_space_mb += size
                except Exception as e:
                    failed_items.append(f"向量数据库: {e}")

        # 删除图片
        if "images" in parts:
            images_dir = PDF_IMAGE_DIR / doc_name_base
            if images_dir.exists():
                try:
                    size = get_dir_size(images_dir)
                    shutil.rmtree(images_dir)
                    deleted_items.append(f"图片 ({size:.2f} MB)")
                    freed_space_mb += size
                except Exception as e:
                    failed_items.append(f"图片: {e}")

        # 删除摘要文件
        if "summary" in parts:
            # Check for different summary file naming patterns
            for suffix in ['_brief_summary', '_summary', '']:
                for ext in ['.md', '.pdf']:
                    summary_file = OUTPUT_DIR / f"{doc_name_base}{suffix}{ext}"
                    if summary_file.exists():
                        try:
                            size = get_dir_size(summary_file)
                            summary_file.unlink()
                            deleted_items.append(f"摘要 ({ext}) ({size:.2f} MB)")
                            freed_space_mb += size
                        except Exception as e:
                            failed_items.append(f"摘要 ({ext}): {e}")

        # 删除本地源 PDF 文件（需显式指定 "pdf"，"all" 不包含它）
        if "pdf" in parts:
            source_pdf = get_source_pdf_path(doc_name_base, doc_info)
            if source_pdf is not None:
                try:
                    size = get_dir_size(source_pdf)
                    source_pdf.unlink()
                    deleted_items.append(f"源 PDF 文件 ({size:.2f} MB)")
                    freed_space_mb += size
                    print(f"✓ 已删除源 PDF 文件: {source_pdf}")
                except Exception as e:
                    failed_items.append(f"源 PDF 文件: {e}")
            else:
                print(f"ℹ️  未找到 {doc_name_base} 的源 PDF 文件，跳过")

        # 如果删除了所有部分，则从注册表和元数据向量数据库中删除
        if "registry" in parts or set(parts) >= {"json", "vector_db", "images", "summary"}:
            # 只有当Registry中有记录时才尝试删除Registry和MetadataDB
            if doc_info:
                doc_id = doc_info["doc_id"]

                # 1. 先从 MetadataVectorDB 中删除元数据（在 Registry 删除之前）
                # 这样 MetadataDB.delete_document() 可以从 Registry 中获取 doc_name 用于日志
                # 仅在元数据索引文件存在时尝试加载和删除
                try:
                    metadata_index_file = DATA_DIR / "vector_db" / "_metadata" / "index.faiss"

                    if metadata_index_file.exists():
                        from src.core.vector_db.metadata_db import MetadataVectorDB
                        metadata_db = MetadataVectorDB()
                        if metadata_db.delete_document(doc_id):
                            deleted_items.append("元数据向量数据库记录")
                            print(f"✓ 已从 MetadataVectorDB 中删除元数据: {doc_name}")
                        else:
                            failed_items.append("元数据向量数据库: 删除未完全成功")
                    else:
                        print(f"ℹ️  元数据向量数据库未初始化，跳过删除")
                except Exception as meta_e:
                    failed_items.append(f"元数据向量数据库: {meta_e}")
                    print(f"⚠️ 从 MetadataVectorDB 删除失败: {meta_e}")

                # 2. 再从 DocumentRegistry 中删除
                try:
                    registry.delete(doc_id)
                    deleted_items.append("注册表记录")
                except Exception as e:
                    failed_items.append(f"注册表记录: {e}")
            else:
                # Registry中没有记录，记录一个警告但不算失败
                print(f"⚠️  文档 {doc_name} 在Registry中不存在，跳过Registry删除")

        # 如果什么都没删除（文件不存在且Registry也没记录），返回404
        if len(deleted_items) == 0 and not doc_info:
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_name}")

        return {
            "status": "success" if len(failed_items) == 0 else "partial",
            "doc_name": doc_name,
            "deleted": deleted_items,
            "failed": failed_items,
            "freed_space_mb": round(freed_space_mb, 2)
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 删除文档部分失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents")
async def batch_delete_documents(request: BatchDeleteRequest):
    """
    批量删除文档（完整删除）

    Args:
        request: 批量删除请求

    Returns:
        删除结果汇总
    """
    try:
        results = {
            "total": len(request.doc_names),
            "success": 0,
            "failed": 0,
            "details": [],
            "total_freed_mb": 0.0
        }

        for doc_name in request.doc_names:
            try:
                # 逐条做目录穿越校验，非法名称直接记为失败（不静默跳过、不删除）
                try:
                    safe_path(DATA_DIR, doc_name)
                except ValueError as guard_e:
                    results["failed"] += 1
                    results["details"].append({
                        "doc_name": doc_name,
                        "status": "failed",
                        "reason": f"非法文档名: {guard_e}"
                    })
                    continue

                # 直接调用 delete_document_parts，不预检查
                # 这样可以删除孤立文件（Registry 中无记录但文件存在）
                parts = ["all", "pdf"] if request.delete_source else ["all"]
                delete_result = await delete_document_parts(
                    doc_name,
                    DeletePartsRequest(parts=parts)
                )

                results["success"] += 1
                results["total_freed_mb"] += delete_result["freed_space_mb"]
                results["details"].append({
                    "doc_name": doc_name,
                    "status": "success",
                    "freed_mb": delete_result["freed_space_mb"]
                })

            except HTTPException as e:
                # 处理 HTTP 异常（如 404 - 文档不存在）
                results["failed"] += 1
                results["details"].append({
                    "doc_name": doc_name,
                    "status": "failed",
                    "reason": e.detail if hasattr(e, 'detail') else str(e)
                })

            except Exception as e:
                # 处理其他异常
                results["failed"] += 1
                results["details"].append({
                    "doc_name": doc_name,
                    "status": "failed",
                    "reason": str(e)
                })

        return results

    except Exception as e:
        print(f"❌ 批量删除失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cache/{cache_type}")
async def get_cache_info(cache_type: str):
    """
    获取缓存信息

    Args:
        cache_type: 缓存类型 (pdf_image, vector_db, json_data)

    Returns:
        缓存信息
    """
    try:
        cache_dirs = {
            "pdf_image": PDF_IMAGE_DIR,
            "vector_db": VECTOR_DB_DIR,
            "json_data": JSON_DATA_DIR
        }

        if cache_type not in cache_dirs:
            raise HTTPException(
                status_code=400,
                detail=f"无效的缓存类型: {cache_type}"
            )

        cache_dir = cache_dirs[cache_type]

        if not cache_dir.exists():
            return {
                "type": cache_type,
                "size_mb": 0.0,
                "items": 0
            }

        # Count items (subdirectories or files)
        items = list(cache_dir.iterdir())

        return {
            "type": cache_type,
            "size_mb": round(get_dir_size(cache_dir), 2),
            "items": len(items)
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 获取缓存信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cache/{cache_type}")
async def clear_cache(cache_type: str):
    """
    清空缓存

    Args:
        cache_type: 缓存类型 (pdf_image, vector_db, json_data)

    Returns:
        清空结果
    """
    try:
        cache_dirs = {
            "pdf_image": PDF_IMAGE_DIR,
            "vector_db": VECTOR_DB_DIR,
            "json_data": JSON_DATA_DIR
        }

        if cache_type not in cache_dirs:
            raise HTTPException(
                status_code=400,
                detail=f"无效的缓存类型: {cache_type}"
            )

        cache_dir = cache_dirs[cache_type]

        if not cache_dir.exists():
            return {
                "status": "success",
                "message": "缓存目录不存在",
                "freed_mb": 0.0
            }

        # Calculate size before deletion
        size_before = get_dir_size(cache_dir)

        # Delete and recreate directory
        shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        return {
            "status": "success",
            "message": f"已清空 {cache_type} 缓存",
            "freed_mb": round(size_before, 2)
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 清空缓存失败: {e}")
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


@router.post("/backup")
async def create_backup():
    """
    创建数据备份

    Returns:
        备份信息
    """
    try:
        backup_dir = DATA_DIR / "backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)

        backed_up = []

        # Backup sessions
        sessions_src = DATA_DIR / "sessions"
        if sessions_src.exists():
            shutil.copytree(sessions_src, backup_dir / "sessions", dirs_exist_ok=True)
            backed_up.append("sessions")

        # Backup doc registry
        registry_file = DATA_DIR / "doc_registry.json"
        if registry_file.exists():
            shutil.copy2(registry_file, backup_dir / "doc_registry.json")
            backed_up.append("doc_registry")

        # Backup output (summaries)
        if OUTPUT_DIR.exists():
            shutil.copytree(OUTPUT_DIR, backup_dir / "output", dirs_exist_ok=True)
            backed_up.append("output")

        backup_size = get_dir_size(backup_dir)

        return {
            "status": "success",
            "backup_path": str(backup_dir),
            "backed_up": backed_up,
            "size_mb": round(backup_size, 2),
            "created_at": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"❌ 创建备份失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
async def full_system_reset(confirm: str = Query(...)):
    """
    完全重置系统（危险操作）

    Args:
        confirm: 确认字符串（必须是 "CONFIRM_RESET"）

    Returns:
        重置结果
    """
    if confirm != "CONFIRM_RESET":
        raise HTTPException(
            status_code=400,
            detail="必须提供确认字符串 'CONFIRM_RESET'"
        )

    try:
        # Create backup first
        backup_result = await create_backup()

        deleted_items = []
        freed_space_mb = 0.0

        # Delete all data directories
        data_dirs = [
            JSON_DATA_DIR,
            VECTOR_DB_DIR,
            PDF_IMAGE_DIR,
            OUTPUT_DIR,
            DATA_DIR / "sessions"
        ]

        for dir_path in data_dirs:
            if dir_path.exists():
                size = get_dir_size(dir_path)
                shutil.rmtree(dir_path)
                dir_path.mkdir(parents=True, exist_ok=True)
                deleted_items.append(str(dir_path.name))
                freed_space_mb += size

        # Reset document registry
        registry_file = DATA_DIR / "doc_registry.json"
        if registry_file.exists():
            registry_file.unlink()
            deleted_items.append("doc_registry.json")

        return {
            "status": "success",
            "message": "系统已完全重置",
            "backup": backup_result,
            "deleted": deleted_items,
            "freed_mb": round(freed_space_mb, 2)
        }

    except Exception as e:
        print(f"❌ 系统重置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
