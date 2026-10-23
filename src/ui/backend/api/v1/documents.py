"""文档管理 API"""

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from pathlib import Path

from ...config import PDF_DIR

from src.config.settings import resolve_provider
from src.core.document_management import DocumentRegistry
# 删除的唯一权威实现（REFACTOR_REPORT P2-1）：本模块不再自己 rmtree / 注销注册表，
# 只负责把 core 的结构化结果翻译成 HTTP 状态码与响应体。
from src.core.document_management.delete_service import (
    PART_METADATA_DB,
    DeleteItem,
    delete_document_service,
)
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
    provider: Optional[str] = None  # 省略 = 跟随 /config 页选择（resolve_provider 链）
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
        indexing_agent = IndexingAgent(provider=resolve_provider(provider), pdf_preset=pdf_preset)

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


#: core 部件名 → 本端点响应体的历史文案（前端 manage.js 不看这个字段，
#: 但字段名与取值口径保持不变，避免无谓的行为漂移）
_DELETED_ITEM_LABELS = {
    "json_data": "JSON数据",
    "vector_db": "向量数据库",
    "images": "PDF图像",
    "summary": "输出文件({detail})",
    "brief": "输出文件({detail})",
    "generated": "登记产物({name})",
    "source_pdf": "源PDF文件",
    PART_METADATA_DB: "元数据记录",
}


def _deleted_item_label(item: DeleteItem) -> str:
    """把 core 的删除记录翻译成本端点历史响应体里的中文条目。"""
    template = _DELETED_ITEM_LABELS.get(item.part, item.part)
    name = Path(item.path).name if item.path else ""
    return template.format(detail=item.detail or "", name=name)


@router.delete("/{doc_name}")
async def delete_document(doc_name: str) -> Dict[str, Any]:
    """
    删除文档及其所有相关数据

    清理逻辑不在本模块：一律委托 core 层唯一实现
    :func:`src.core.document_management.delete_service.delete_document_service`
    （registry 注销、索引目录删除、brief 文件清理的唯一权威出处，路径统一过
    ``safe_path``，删完向量库还会作废读侧索引缓存）。本端点只做三件事：
    parts 映射（本入口是全删）、非法名 → 400、响应体文案。

    Args:
        doc_name: 文档名称

    Returns:
        删除结果
    """
    try:
        # parts=None → 全删（与既有语义一致：不含 data/pdf 下的源文件）；
        # core 内部对 doc_name 过 safe_path，越界抛 ValueError → 400
        try:
            result = delete_document_service(doc_name)
        except ValueError as guard_e:
            raise HTTPException(status_code=400, detail=f"非法文档名: {guard_e}")

        deleted_items = [_deleted_item_label(item) for item in result.deleted]
        if result.registry_removed:
            deleted_items.append("注册表记录")
        freed_space_mb = result.freed_space_mb

        # 与旧实现一致：产物删除 / 注册表注销失败 → 500；
        # 元数据向量库清理失败只告警（旧实现就是 print 后继续）
        hard_failures = [item for item in result.failed if item.part != PART_METADATA_DB]
        if hard_failures:
            detail = "; ".join(
                f"{_deleted_item_label(item)}: {item.error}" for item in hard_failures
            )
            print(f"❌ 删除文档失败: {detail}")
            raise HTTPException(status_code=500, detail=detail)

        if not deleted_items:
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_name}")

        for item in result.failed:
            print(f"⚠️ {_deleted_item_label(item)} 清理失败: {item.error}")

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
