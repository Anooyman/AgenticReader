"""PDF 文件服务 API"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Dict, Any, List

from ...config import PDF_DIR, PDF_IMAGE_DIR

router = APIRouter()


@router.get("/view/{doc_name}")
async def view_pdf(doc_name: str):
    """查看PDF文件"""
    try:
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


@router.get("/images/{doc_name}")
async def get_pdf_images(doc_name: str) -> Dict[str, Any]:
    """获取PDF图片列表"""
    try:
        pdf_image_dir = PDF_IMAGE_DIR / doc_name

        if not pdf_image_dir.exists():
            return {
                "success": False,
                "message": f"PDF图片目录不存在: {doc_name}",
                "images": []
            }

        # 获取所有PNG图片并按页码排序
        image_files = list(pdf_image_dir.glob("*.png"))

        # 按页码排序（从文件名中提取数字）
        def extract_page_num(filepath):
            import re
            match = re.search(r'page_(\d+)', filepath.name)
            return int(match.group(1)) if match else 0

        image_files = sorted(image_files, key=extract_page_num)

        images = []
        for image_file in image_files:
            # 构建相对URL路径
            image_url = f"/api/v1/pdf/image/{doc_name}/{image_file.name}"
            images.append(image_url)

        return {
            "success": True,
            "doc_name": doc_name,
            "total_pages": len(images),
            "images": images
        }

    except Exception as e:
        print(f"❌ 获取PDF图片失败: {e}")
        return {
            "success": False,
            "message": str(e),
            "images": []
        }


@router.get("/image/{doc_name}/{filename}")
async def get_pdf_image(doc_name: str, filename: str):
    """获取单个PDF图片"""
    try:
        image_path = PDF_IMAGE_DIR / doc_name / filename

        if not image_path.exists():
            raise HTTPException(status_code=404, detail=f"图片不存在: {filename}")

        return FileResponse(
            path=str(image_path),
            media_type='image/png',
            filename=filename
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 获取PDF图片失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
