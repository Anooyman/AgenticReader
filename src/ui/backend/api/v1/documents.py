"""文档管理 API"""

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import shutil
from pathlib import Path

from ...config import PDF_DIR, JSON_DATA_DIR, VECTOR_DB_DIR, PDF_IMAGE_DIR, OUTPUT_DIR
from src.core.document_management import DocumentRegistry

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


@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...)) -> Dict[str, Any]:
    """上传PDF文件"""
    try:
        if not file.filename.endswith('.pdf'):
            raise HTTPException(status_code=400, detail="只支持PDF文件")

        # 保存文件
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        file_path = PDF_DIR / file.filename

        if file_path.exists():
            raise HTTPException(status_code=409, detail=f"文件已存在: {file.filename}")

        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        return {
            "status": "success",
            "filename": file.filename,
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
        pdf_path = PDF_DIR / request.doc_name
        if not pdf_path.exists():
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

        # 执行索引
        result = await indexing_agent.graph.ainvoke({
            "doc_name": doc_name_clean,
            "doc_path": str(pdf_path),
            "is_complete": False
        })

        if result.get("is_complete"):
            print(f"✅ 文档索引完成: {doc_name}")
        else:
            print(f"❌ 文档索引失败: {doc_name}")

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

        # 删除向量数据库
        vector_db_path = VECTOR_DB_DIR / doc_name_base
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

        # 删除输出文件（摘要）
        for ext in ['.md', '.pdf']:
            output_file = OUTPUT_DIR / f"{doc_name_base}{ext}"
            if output_file.exists():
                size = output_file.stat().st_size / (1024 * 1024)
                output_file.unlink()
                deleted_items.append(f"输出文件({ext})")
                freed_space_mb += size

        # 从 DocumentRegistry 中删除
        doc_info = registry.get_by_name(doc_name_base)
        if doc_info:
            doc_id = doc_info.get("doc_id")
            if doc_id:
                # 删除元数据向量数据库记录（仅在索引文件存在时尝试）
                try:
                    from pathlib import Path
                    from src.config.settings import DATA_ROOT
                    metadata_index_file = Path(DATA_ROOT) / "vector_db" / "_metadata" / "index.faiss"

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
