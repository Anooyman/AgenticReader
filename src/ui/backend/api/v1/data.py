"""数据管理 API——文档产物域（REFACTOR_REPORT P2-4，原 data.py 拆分后保留本域）

本模块负责 /data 页的文档类端点：文档产物详细清单（GET /documents，含
元数据与 JSON/向量库/图片/摘要/PDF 五类大小）、单文档摘要（GET
/documents/{doc_name}/summary）、部分删除（DELETE /documents/{doc_name}/parts）
与批量完全删除（DELETE /documents）。

存储类（overview / pending PDFs / sessions stats / smart cleanup）在
``data_storage.py``，任务类（index 启动 / tasks 查询）在 ``data_ops.py``，
跨模块共享 helper 在 ``data_common.py``。URL 前缀 ``/api/v1/data`` 由
app.py 的 include_router 统一提供，各模块路由路径与拆分前逐条一致。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
from pathlib import Path

from ...config import (
    JSON_DATA_DIR, PDF_IMAGE_DIR, DATA_DIR
)
from src.core.document_management import DocumentRegistry
# 删除的唯一权威实现（REFACTOR_REPORT P2-1）：rmtree / registry 注销 / brief 清理
# 全部在 core 里，本模块只做 parts 映射与响应体（status / deleted / failed）的翻译。
from src.core.document_management.delete_service import (
    DeleteItem,
    delete_document_service,
    find_source_pdf,
)
from src.config.constants import (
    get_summary_paths,
    get_vector_db_path,
)
from src.utils.path_guard import safe_path
from .data_common import get_dir_size

router = APIRouter()


# ==================== Pydantic Models ====================

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


class DeletePartsRequest(BaseModel):
    """删除部分数据的请求"""
    parts: List[str]  # ["json", "vector_db", "images", "summary", "pdf", "all"]


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""
    doc_names: List[str]
    delete_source: bool = False  # 是否同时删除本地源 PDF 文件


# ==================== Helper Functions ====================

def get_source_pdf_path(doc_name_base: str, doc_info: Optional[Dict] = None) -> Optional[Path]:
    """
    定位文档的本地源 PDF 文件

    委托 core 层唯一实现 ``delete_service.find_source_pdf``——数据管理页统计的
    has_pdf / pdf_size_mb 与「完全删除」实际删掉的那个文件因此不会各拼一套。

    优先使用 data/pdf/{name}.pdf（上传/索引时使用的目录），
    其次回退到注册表里记录的 doc_path（可能是外部路径）。

    Args:
        doc_name_base: 文档名称（不含 .pdf 扩展名）
        doc_info: 注册表中的文档信息（可选）

    Returns:
        存在的源文件路径，找不到则返回 None
    """
    return find_source_pdf(doc_name_base, doc_info)


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

    # Vector DB（目录名 = 文档名 + 索引后缀，由 constants helper 统一生成）
    vector_db_path = get_vector_db_path(doc_name_base)
    if vector_db_path.exists():
        sizes["vector_db_size_mb"] = get_dir_size(vector_db_path)
        sizes["has_vector_db"] = True

    # Images (in pdf_image/{doc_name_base}/ directory)
    images_dir = PDF_IMAGE_DIR / doc_name_base
    if images_dir.exists():
        sizes["images_size_mb"] = get_dir_size(images_dir)
        sizes["has_images"] = True

    # Summary files (MD and PDF in output directory)
    # 摘要命名（_brief_summary / _summary / 无后缀 × .md/.pdf）与索引落盘处同源
    for summary_file in get_summary_paths(doc_name_base):
        if summary_file.exists():
            sizes["summary_size_mb"] += get_dir_size(summary_file)
            sizes["has_summary"] = True

    # Source PDF file (in pdf/ directory or registered doc_path)
    source_pdf = get_source_pdf_path(doc_name_base, doc_info)
    if source_pdf is not None:
        sizes["pdf_size_mb"] = get_dir_size(source_pdf)
        sizes["has_pdf"] = True

    return sizes


#: core 部件名 → 本端点历史响应体里的条目文案模板（字段与文案口径保持不变，
#: 前端 manage.js 零改动）
_PART_DELETED_LABELS = {
    "json_data": "JSON 数据 ({size:.2f} MB)",
    "vector_db": "向量数据库 ({size:.2f} MB)",
    "images": "图片 ({size:.2f} MB)",
    "summary": "摘要 ({detail}) ({size:.2f} MB)",
    "brief": "摘要 ({detail}) ({size:.2f} MB)",
    "generated": "登记产物 ({name}) ({size:.2f} MB)",
    "source_pdf": "源 PDF 文件 ({size:.2f} MB)",
    "metadata_db": "元数据向量数据库记录",
}

_PART_FAILED_LABELS = {
    "json_data": "JSON 数据",
    "vector_db": "向量数据库",
    "images": "图片",
    "summary": "摘要 ({detail})",
    "brief": "摘要 ({detail})",
    "generated": "登记产物 ({name})",
    "source_pdf": "源 PDF 文件",
    "metadata_db": "元数据向量数据库",
    "registry": "注册表记录",
}


def _part_deleted_label(item: DeleteItem) -> str:
    """core 的成功记录 → 历史 deleted 条目文案。"""
    template = _PART_DELETED_LABELS.get(item.part, item.part + " ({size:.2f} MB)")
    name = Path(item.path).name if item.path else ""
    return template.format(size=item.size_mb, detail=item.detail or "", name=name)


def _part_failed_label(item: DeleteItem) -> str:
    """core 的失败记录 → 历史 failed 条目文案。"""
    template = _PART_FAILED_LABELS.get(item.part, item.part)
    name = Path(item.path).name if item.path else ""
    return f"{template.format(detail=item.detail or '', name=name)}: {item.error}"


# ==================== API Endpoints ====================

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


@router.delete("/documents/{doc_name}/parts")
async def delete_document_parts(doc_name: str, request: DeletePartsRequest):
    """
    删除文档的指定部分数据（粒度控制）

    清理逻辑不在本模块：一律委托 core 层唯一实现
    :func:`src.core.document_management.delete_service.delete_document_service`
    （registry 注销、索引目录删除、brief 文件清理的唯一权威出处；路径统一过
    ``safe_path``，删完向量库还会作废读侧索引缓存）。本端点只做 parts 映射与
    响应体（status / deleted / failed / freed_space_mb）的翻译，
    非法文档名 → 400、什么都没删到 → 404 的既有语义不变。

    Args:
        doc_name: 文档名称
        request: 删除请求（包含要删除的部分）

    Returns:
        删除结果
    """
    try:
        # 注意：即使 Registry 中没有记录，core 也会继续尝试删除文件，
        # 这样可以清理孤立的文件（Registry 已被删除但文件还在的情况）
        try:
            result = delete_document_service(doc_name, parts=request.parts)
        except ValueError as guard_e:
            # 目录穿越防护：doc_name 会派生出多个数据目录路径，
            # core 内部统一校验名称不越过 DATA_DIR，杜绝通过 "../" 删除外部内容
            raise HTTPException(status_code=400, detail=f"非法文档名: {guard_e}")

        deleted_items = [_part_deleted_label(item) for item in result.deleted]
        if result.registry_removed:
            deleted_items.append("注册表记录")
        failed_items = [_part_failed_label(item) for item in result.failed]
        freed_space_mb = result.freed_space_mb

        if "source_pdf" in result.deleted_parts:
            print(f"✓ 已删除源 PDF 文件: {[i.path for i in result.deleted if i.part == 'source_pdf']}")

        # 如果什么都没删除（文件不存在且Registry也没记录），返回404
        if len(deleted_items) == 0 and not result.doc_info:
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
