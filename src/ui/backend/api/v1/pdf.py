"""PDF相关API端点"""

import os
import sys
import logging
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, BackgroundTasks
from fastapi.responses import FileResponse

# 添加项目根路径到sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ...config import get_logger, settings
from ...core.exceptions import PDFNotFoundError, PDFProcessingError
from ...models.document import PDFImageList, PDFImage
from ...services.session_service import SessionService
from ...services.chat_service import chat_service

# 导入PDF处理器
try:
    from src.readers.pdf import PDFReader
except ImportError as e:
    logger = get_logger(__name__)
    logger.error(f"无法导入PDFReader: {e}")
    PDFReader = None

router = APIRouter(prefix="/pdf", tags=["PDF"])
logger = get_logger(__name__)


async def process_pdf_async(filename: str, provider: str = "openai", pdf_preset: str = "high"):
    """异步处理PDF文件"""
    try:
        if PDFReader is None:
            logger.error("PDFReader未正确导入")
            return False

        # 初始化PDF阅读器
        pdf_reader = PDFReader(provider=provider, pdf_preset=pdf_preset)

        # 获取文档名（不包含.pdf后缀）
        doc_name = filename.replace('.pdf', '') if filename.endswith('.pdf') else filename

        logger.info(f"🔄 开始处理PDF文件: {doc_name}")

        # 调用PDF处理方法（这会进行完整的处理流程）
        pdf_reader.process_pdf(doc_name, save_data_flag=True)

        logger.info(f"✅ PDF处理完成: {doc_name}")

        # 初始化聊天服务
        logger.info(f"🔄 初始化聊天服务: {doc_name}")
        chat_initialized = chat_service.initialize_pdf_reader(doc_name, provider=provider, pdf_preset=pdf_preset)

        if chat_initialized:
            logger.info(f"✅ 聊天服务初始化成功: {doc_name}")
        else:
            logger.warning(f"⚠️ 聊天服务初始化失败: {doc_name}")

        return True

    except Exception as e:
        logger.error(f"❌ PDF处理失败: {str(e)}")
        return False


@router.post("/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    provider: str = "openai",
    pdf_preset: str = "high",
    session_service: SessionService = Depends()
):
    """上传并处理PDF文件"""
    try:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="只支持PDF文件")

        # 保存文件到PDF目录
        pdf_dir = settings.data_dir / "pdf"
        pdf_dir.mkdir(parents=True, exist_ok=True)

        file_path = pdf_dir / file.filename
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        logger.info(f"✅ PDF文件上传成功: {file.filename}")

        # 获取文档名（不包含.pdf后缀）
        doc_name = file.filename.replace('.pdf', '') if file.filename.endswith('.pdf') else file.filename

        # 添加后台处理任务
        background_tasks.add_task(process_pdf_async, file.filename, provider, pdf_preset)

        return {
            "status": "processing",
            "message": f"PDF文件已上传，正在后台处理中...",
            "doc_name": doc_name,
            "filename": file.filename,
            "size": len(content)
        }

    except Exception as e:
        logger.error(f"❌ PDF上传失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"PDF上传失败: {str(e)}")


@router.get("/file/{doc_name}")
async def get_pdf_file(doc_name: str):
    """获取PDF文件"""
    try:
        pdf_path = settings.data_dir / "pdf" / f"{doc_name}.pdf"

        if not pdf_path.exists():
            # 也检查没有.pdf后缀的情况
            pdf_path = settings.data_dir / "pdf" / doc_name
            if not pdf_path.exists():
                raise PDFNotFoundError(f"PDF文件不存在: {doc_name}")

        return FileResponse(
            path=str(pdf_path),
            media_type='application/pdf',
            filename=f"{doc_name}.pdf"
        )

    except PDFNotFoundError:
        raise HTTPException(status_code=404, detail=f"PDF文件不存在: {doc_name}")
    except Exception as e:
        logger.error(f"❌ 获取PDF文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取PDF文件失败: {str(e)}")


@router.get("/images/{doc_name}", response_model=PDFImageList)
async def get_pdf_images(doc_name: str):
    """获取PDF图片列表"""
    try:
        pdf_image_dir = settings.data_dir / "pdf_image" / doc_name

        if not pdf_image_dir.exists():
            raise PDFNotFoundError(f"PDF图片目录不存在: {doc_name}")

        images = []
        image_files = sorted(pdf_image_dir.glob("*.png"))

        for i, image_file in enumerate(image_files, 1):
            # 构建相对URL路径 - 正确的API前缀是 /api/v1/pdf/image/
            image_url = f"/api/v1/pdf/image/{doc_name}/{image_file.name}"
            images.append(PDFImage(
                page=i,
                url=image_url,
                filename=image_file.name
            ))

        if not images:
            logger.warning(f"⚠️ PDF图片目录为空: {doc_name}")

        return PDFImageList(
            doc_name=doc_name,
            total_pages=len(images),
            images=images
        )

    except PDFNotFoundError:
        raise HTTPException(status_code=404, detail=f"PDF图片不存在: {doc_name}")
    except Exception as e:
        logger.error(f"❌ 获取PDF图片失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取PDF图片失败: {str(e)}")


@router.get("/image/{doc_name}/{filename}")
async def get_pdf_image(doc_name: str, filename: str):
    """获取单个PDF图片"""
    try:
        image_path = settings.data_dir / "pdf_image" / doc_name / filename

        if not image_path.exists():
            raise HTTPException(status_code=404, detail=f"图片不存在: {filename}")

        return FileResponse(
            path=str(image_path),
            media_type='image/png',
            filename=filename
        )

    except Exception as e:
        logger.error(f"❌ 获取PDF图片失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取PDF图片失败: {str(e)}")


@router.get("/status/{doc_name}")
async def get_processing_status(doc_name: str):
    """获取PDF处理状态"""
    try:
        # 检查各种处理阶段的文件是否存在
        pdf_path = settings.data_dir / "pdf" / f"{doc_name}.pdf"
        if not pdf_path.exists():
            pdf_path = settings.data_dir / "pdf" / doc_name
            if not pdf_path.exists():
                return {"status": "not_found", "message": "PDF文件不存在"}

        json_path = settings.data_dir / "json_data" / f"{doc_name}.json"
        vector_path = settings.data_dir / "vector_db" / f"{doc_name}_data_index"

        has_json = json_path.exists()
        has_vector = vector_path.exists() and any(vector_path.iterdir())

        logger.info(f"📊 检查处理状态 - 文档: {doc_name}")
        logger.info(f"📄 JSON路径: {json_path}, 存在: {has_json}")
        logger.info(f"🗂️ 向量路径: {vector_path}, 存在: {has_vector}")

        if has_json and has_vector:
            return {
                "status": "completed",
                "message": "PDF处理完成",
                "has_json": True,
                "has_vector": True
            }
        elif has_json:
            return {
                "status": "processing",
                "message": "PDF基础处理完成，向量化进行中",
                "has_json": True,
                "has_vector": False
            }
        else:
            return {
                "status": "processing",
                "message": "PDF处理中...",
                "has_json": False,
                "has_vector": False
            }

    except Exception as e:
        logger.error(f"❌ 获取处理状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取处理状态失败: {str(e)}")


@router.get("/summary/{doc_name}")
async def get_pdf_summary(doc_name: str, summary_type: str = "brief"):
    """获取PDF摘要"""
    try:
        # 检查摘要文件 - 优先查找新格式，然后查找旧格式
        if summary_type == "brief":
            # 先尝试新格式路径
            summary_file = settings.data_dir / "output" / f"{doc_name}_summary_brief.md"
            # 如果不存在，尝试旧格式路径（按文档目录存储）
            if not summary_file.exists():
                summary_file = settings.data_dir / "output" / doc_name / "brief_summary.md"
        else:
            # 先尝试新格式路径（detailed）
            summary_file = settings.data_dir / "output" / f"{doc_name}_summary_detailed.md"
            # 如果不存在，尝试旧格式路径（按文档目录存储）
            if not summary_file.exists():
                summary_file = settings.data_dir / "output" / doc_name / "detail_summary.md"

        if not summary_file.exists():
            return {
                "status": "not_ready",
                "message": f"{summary_type}摘要尚未生成，请等待处理完成",
                "content": ""
            }

        # 读取摘要内容
        content = summary_file.read_text(encoding='utf-8')
        
        # 🔥 修复：去除 LLM 生成的代码块包裹符号
        # 某些 LLM 会将整个 Markdown 内容包裹在 ```markdown``` 或 ``` 中
        content = content.strip()
        if content.startswith('```'):
            # 去除开头的 ``` 或 ```markdown
            lines = content.split('\n')
            if lines[0].strip().startswith('```'):
                lines = lines[1:]  # 去掉第一行
            # 去除结尾的 ```
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]  # 去掉最后一行
            content = '\n'.join(lines)

        return {
            "status": "success",
            "summary_type": summary_type,
            "content": content,
            "file": str(summary_file)
        }

    except Exception as e:
        logger.error(f"❌ 获取PDF摘要失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取PDF摘要失败: {str(e)}")


@router.post("/reinitialize/{doc_name}")
async def reinitialize_pdf(
    doc_name: str,
    session_service: SessionService = Depends()
):
    """重新初始化PDF阅读器（用于历史会话恢复）"""
    try:
        # 导入全局配置
        from .config import _current_config

        # 检查PDF文件是否存在
        pdf_path = settings.data_dir / "pdf" / f"{doc_name}.pdf"
        if not pdf_path.exists():
            pdf_path = settings.data_dir / "pdf" / doc_name
            if not pdf_path.exists():
                raise PDFNotFoundError(f"PDF文件不存在: {doc_name}")

        # 检查JSON数据是否存在
        json_path = settings.data_dir / "json_data" / f"{doc_name}.json"
        if not json_path.exists():
            logger.warning(f"⚠️ JSON数据文件不存在，需要重新处理PDF: {doc_name}")
            return {
                "status": "needs_processing",
                "message": f"PDF {doc_name} 需要重新处理",
                "doc_name": doc_name,
                "has_pdf": True,
                "has_json": False
            }

        # 初始化聊天服务
        logger.info(f"🔄 正在初始化聊天服务: {doc_name}")
        logger.info(f"📊 初始化前ChatService状态: {chat_service.get_status()}")

        success = chat_service.initialize_pdf_reader(doc_name, provider="openai", pdf_preset="high")

        logger.info(f"📊 初始化后ChatService状态: {chat_service.get_status()}")

        if success:
            # 🔥 新增：更新全局配置状态
            from .config import update_document_state
            update_document_state(doc_name, has_pdf_reader=True, has_web_reader=False)

            logger.info(f"✅ PDF阅读器和聊天服务重新初始化成功: {doc_name}")
            return {
                "status": "success",
                "message": f"PDF阅读器已重新初始化: {doc_name}",
                "doc_name": doc_name,
                "has_pdf": True,
                "has_json": True,
                "chat_initialized": True
            }
        else:
            logger.warning(f"⚠️ 聊天服务初始化失败: {doc_name}")
            return {
                "status": "partial_success",
                "message": f"PDF文件检查完成，但聊天服务初始化失败: {doc_name}",
                "doc_name": doc_name,
                "has_pdf": True,
                "has_json": True,
                "chat_initialized": False
            }

    except PDFNotFoundError:
        raise HTTPException(status_code=404, detail=f"PDF文件不存在: {doc_name}")
    except Exception as e:
        logger.error(f"❌ PDF重新初始化失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"PDF重新初始化失败: {str(e)}")