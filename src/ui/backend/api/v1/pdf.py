"""PDF 文件服务 API"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ...config import PDF_DIR
from src.utils.path_guard import safe_path

router = APIRouter()


@router.get("/view/{doc_name}")
async def view_pdf(doc_name: str):
    """查看PDF文件"""
    try:
        # 目录穿越防护
        try:
            safe_path(PDF_DIR, doc_name)
        except ValueError as guard_e:
            raise HTTPException(status_code=400, detail=f"非法文档名: {guard_e}")

        # 支持带 .pdf 和不带 .pdf 后缀
        pdf_path = PDF_DIR / doc_name
        if not pdf_path.exists():
            pdf_path = PDF_DIR / f"{doc_name}.pdf"

        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail=f"PDF文件不存在: {doc_name}")

        return FileResponse(
            path=str(pdf_path),
            media_type='application/pdf',
            filename=pdf_path.name
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 获取PDF文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
