"""文档管理 API"""

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import shutil
from pathlib import Path

from ...config import PDF_DIR, JSON_DATA_DIR, PDF_IMAGE_DIR, DATA_DIR

from src.config.constants import (
    get_metadata_db_path,
    get_summary_paths,
    get_vector_db_path,
)
from src.core.document_management import DocumentRegistry
from src.utils.path_guard import safe_path

router = APIRouter()


class DocumentInfo(BaseModel):
    """文档信息"""
    doc_name: str
    doc_type: str
    brief_summary: Optional[str] = None
    index_path: Optional[str] = None


class IndexRequest(BaseModel):
    """索引请求"""
    doc_name: str
    provider: str = "openai"
    pdf_preset: str = "high"


@router.get("/list")
async def list_documents() -> List[DocumentInfo]:
    """获取已索引文档列表"""
    try:
        registry = DocumentRegistry()
        all_docs = registry.list_all()

        documents = []
        for doc in all_docs:
            # 检查是否有向量数据库
            index_path = doc.get("index_path")
            if index_path and Path(index_path).exists():
                documents.append(DocumentInfo(
                    doc_name=doc.get("doc_name", ""),
                    doc_type=doc.get("doc_type", "pdf"),
                    brief_summary=doc.get("brief_summary"),
                    index_path=index_path
                ))

        return documents

    except Exception as e:
        print(f"❌ 获取文档列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/available-pdfs")
async def get_available_pdfs() -> List[str]:
    """获取待索引的PDF文件"""
    try:
        if not PDF_DIR.exists():
            return []

        # 获取所有PDF文件
        all_pdfs = [f.name for f in PDF_DIR.glob("*.pdf")]

        # 获取已索引的文档（自动过滤.pdf后缀）
        registry = DocumentRegistry()
        indexed_docs = {doc.get("doc_name") for doc in registry.list_all()}

        # 为已索引文档添加.pdf后缀进行比较
        indexed_docs_with_pdf = {f"{doc}.pdf" if not doc.endswith('.pdf') else doc
                                  for doc in indexed_docs}

        # 返回未索引的PDF
        available = [pdf for pdf in all_pdfs if pdf not in indexed_docs_with_pdf]

        return available

    except Exception as e:
        print(f"❌ 获取可用PDF列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 上传单文件大小上限（100MB），超出返回 413
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _sanitize_upload_filename(raw_filename: Optional[str]) -> str:
    """
    清洗 multipart 传入的原始文件名，返回可安全落盘的名称。

    - 仅取 basename，剥离任何目录部分，杜绝绝对路径（pathlib 拼接会丢弃基目录）
      以及 ../ 之类的目录穿越
    - 拒绝空名与以点开头的名称
    - 保留 .pdf 后缀校验（大小写不敏感）
    """
    name = Path(raw_filename or "").name
    if not name:
        raise HTTPException(status_code=400, detail="非法文件名")
    if name.startswith("."):
        raise HTTPException(status_code=400, detail="非法文件名")
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只支持PDF文件")
    return name


@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...)) -> Dict[str, Any]:
    """上传PDF文件"""
    try:
        # 1) 文件名消毒：只保留 basename，拒绝空名/点开头/非 .pdf
        filename = _sanitize_upload_filename(file.filename)

        # 保存文件
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        # 2) 复用 path_guard.safe_path 做目录越界校验（其内部会剥离 .pdf 后缀），
        #    取校验后所在目录 + 原始文件名拼接，落盘位置仍为 data/pdf/原始文件名，
        #    保持「相对目录 + data/pdf + 原始文件名」的既有约定不变
        try:
            guarded = safe_path(PDF_DIR, filename)
        except ValueError as guard_e:
            raise HTTPException(status_code=400, detail=f"非法文件名: {guard_e}")
        file_path = guarded.parent / filename

        if file_path.exists():
            raise HTTPException(status_code=409, detail=f"文件已存在: {filename}")

        # 3) 优先用 Content-Length 快速拒绝超限请求
        content_length = file.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件超过100MB限制")
            except ValueError:
                pass

        written = 0
        try:
            with file_path.open("wb") as buffer:
                # 4) 读取前 5 字节断言 %PDF- 魔数
                header = await file.read(5)
                if len(header) < 5 or not header.startswith(b"%PDF-"):
                    raise HTTPException(status_code=400, detail="文件不是有效的PDF")
                buffer.write(header)
                written += len(header)

                # 流式写入并计数，超过上限立即中断
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="文件超过100MB限制")
                    buffer.write(chunk)
        except HTTPException:
            # 校验未通过或超限：清理可能已创建的半成品文件，再向上抛出
            file_path.unlink(missing_ok=True)
            raise

        return {
            "status": "success",
            "filename": filename,
            "message": "文件上传成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 文件上传失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/index")
async def index_document(
    request: IndexRequest,
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """索引文档（后台任务）"""
    try:
        if not request.doc_name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="只支持PDF文件")
        # Validate the user-supplied name, then preserve its exact filename.
        # safe_path strips a trailing .pdf for validation and therefore is not the path to open.
        guarded = safe_path(PDF_DIR, request.doc_name)
        pdf_path = guarded.parent / request.doc_name
        if not pdf_path.exists() or not pdf_path.is_file():
            raise HTTPException(status_code=404, detail=f"PDF文件不存在: {request.doc_name}")

        # 添加后台任务
        background_tasks.add_task(
            _index_document_task,
            doc_name=request.doc_name,
            provider=request.provider,
            pdf_preset=request.pdf_preset
        )

        return {
            "status": "started",
            "doc_name": request.doc_name,
            "message": "索引任务已启动"
        }

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"❌ 启动索引任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _index_document_task(doc_name: str, provider: str, pdf_preset: str):
    """后台索引任务"""
    try:
        print(f"📄 开始索引文档: {doc_name}")

        from src.agents.indexing import IndexingAgent

        # 去掉 .pdf 后缀
        doc_name_clean = doc_name.replace('.pdf', '')
        pdf_path = PDF_DIR / doc_name

        # 创建索引代理
        indexing_agent = IndexingAgent(provider=provider, pdf_preset=pdf_preset)

        # 执行索引（初始 state 由 IndexingAgent.index_document 统一构造，
        # 其中包含 doc_type——历史上这里手拼 state 漏了 doc_type）
        result = await indexing_agent.index_document(
            doc_name=doc_name_clean,
            doc_path=str(pdf_path),
            doc_type="pdf",
        )

        if result.get("is_complete"):
            print(f"✅ 文档索引完成: {doc_name}")
        else:
            print(f"❌ 文档索引失败: {doc_name}, 错误: {result.get('error') or '未知错误'}")

    except Exception as e:
        print(f"❌ 索引任务执行失败: {e}")
        import traceback
        traceback.print_exc()


@router.delete("/{doc_name}")
async def delete_document(doc_name: str) -> Dict[str, Any]:
    """
    删除文档及其所有相关数据

    Args:
        doc_name: 文档名称

    Returns:
        删除结果
    """
    try:
        registry = DocumentRegistry()

        # 目录穿越防护：doc_name 派生出各数据目录路径，校验其不越过 DATA_DIR
        try:
            safe_path(DATA_DIR, doc_name)
        except ValueError as guard_e:
            raise HTTPException(status_code=400, detail=f"非法文档名: {guard_e}")

        # Strip .pdf extension for correct path lookups
        doc_name_base = doc_name.replace('.pdf', '') if doc_name.endswith('.pdf') else doc_name

        deleted_items = []
        freed_space_mb = 0.0

        # 删除 JSON 数据
        json_dir = JSON_DATA_DIR / doc_name_base
        if json_dir.exists():
            size = sum(f.stat().st_size for f in json_dir.rglob('*') if f.is_file()) / (1024 * 1024)
            shutil.rmtree(json_dir)
            deleted_items.append("JSON数据")
            freed_space_mb += size

        # 删除向量数据库（目录名由 constants helper 统一生成，手抄漏后缀就会
        # 删不到 → FAISS 目录成为孤儿）
        vector_db_path = get_vector_db_path(doc_name_base)
        if vector_db_path.exists():
            size = sum(f.stat().st_size for f in vector_db_path.rglob('*') if f.is_file()) / (1024 * 1024)
            shutil.rmtree(vector_db_path)
            deleted_items.append("向量数据库")
            freed_space_mb += size

        # 删除 PDF 图像
        pdf_image_dir = PDF_IMAGE_DIR / doc_name_base
        if pdf_image_dir.exists():
            size = sum(f.stat().st_size for f in pdf_image_dir.rglob('*') if f.is_file()) / (1024 * 1024)
            shutil.rmtree(pdf_image_dir)
            deleted_items.append("PDF图像")
            freed_space_mb += size

        # 删除输出文件（摘要）：与数据管理页 delete_document_parts 同一套命名，
        # 覆盖 {doc}_brief_summary / {doc}_summary / {doc} × .md/.pdf
        for output_file in get_summary_paths(doc_name_base):
            if output_file.exists():
                size = output_file.stat().st_size / (1024 * 1024)
                output_file.unlink()
                deleted_items.append(f"输出文件({output_file.suffix})")
                freed_space_mb += size

        # 从 DocumentRegistry 中删除
        doc_info = registry.get_by_name(doc_name_base)
        if doc_info:
            doc_id = doc_info.get("doc_id")
            if doc_id:
                # 删除元数据向量数据库记录（仅在索引文件存在时尝试）
                try:
                    metadata_index_file = get_metadata_db_path() / "index.faiss"

                    if metadata_index_file.exists():
                        from src.core.vector_db.metadata_db import MetadataVectorDB
                        metadata_db = MetadataVectorDB()
                        if metadata_db.delete_document(doc_id):
                            deleted_items.append("元数据记录")
                            print(f"✅ 已从元数据向量数据库删除: {doc_name}")
                    else:
                        print(f"ℹ️  元数据向量数据库未初始化，跳过删除")
                except Exception as meta_e:
                    print(f"⚠️ 删除元数据失败: {meta_e}")

                # 删除注册表记录
                registry.delete(doc_id)
                deleted_items.append("注册表记录")

        if not deleted_items:
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_name}")

        print(f"✅ 文档已删除: {doc_name}, 释放空间: {freed_space_mb:.2f}MB")

        return {
            "status": "success",
            "doc_name": doc_name,
            "deleted_items": deleted_items,
            "freed_space_mb": round(freed_space_mb, 2),
            "message": f"文档已删除，释放 {freed_space_mb:.2f}MB"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 删除文档失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
