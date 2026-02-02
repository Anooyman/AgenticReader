"""文档管理 API"""

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import shutil
from pathlib import Path

from ...config import PDF_DIR, JSON_DATA_DIR, VECTOR_DB_DIR
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
