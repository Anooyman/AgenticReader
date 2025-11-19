"""Web内容处理相关API端点"""

import sys
import logging
import asyncio
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel

# 添加项目根路径到sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ...config import get_logger, settings
from ...services.chat_service import chat_service

router = APIRouter(prefix="/web", tags=["Web"])
logger = get_logger(__name__)


class WebProcessRequest(BaseModel):
    url: str
    save_outputs: bool = True


@router.post("/process")
async def process_web_url(request: WebProcessRequest):
    """处理网页URL"""
    try:
        url = request.url.strip()

        if not url or not (url.startswith('http://') or url.startswith('https://')):
            raise HTTPException(status_code=400, detail="请输入有效的URL")

        logger.info(f"🌐 开始处理网页: {url}")

        # 导入WebReader
        from src.readers.web import WebReader
        from src.utils.helpers import extract_name_from_url

        # 生成文档名（基于URL）
        doc_name = extract_name_from_url(url)
        logger.info(f"📝 生成文档名: {doc_name}")

        # 初始化WebReader（使用settings中配置的provider，默认为openai）
        provider = getattr(settings, 'llm_provider', 'openai')
        web_reader = WebReader(provider=provider)

        # 处理网页内容（异步调用）
        await web_reader.process_web(url, save_data_flag=request.save_outputs)

        logger.info(f"✅ 网页内容处理完成: {url} -> {doc_name}")

        # 检查生成的文件
        json_path = settings.data_dir / "json_data" / f"{doc_name}.json"
        has_json = json_path.exists()

        # 检查是否生成了摘要文件
        output_path = settings.data_dir / "output" / doc_name
        has_summary = output_path.exists()

        # 检查是否生成了向量数据库
        vector_db_path = settings.data_dir / "vector_db" / f"{doc_name}_vector_db"
        has_vector_db = vector_db_path.exists()

        return {
            "status": "success",
            "message": f"网页内容处理完成: {url}",
            "doc_name": doc_name,
            "url": url,
            "save_outputs": request.save_outputs,
            "files_generated": {
                "json_data": has_json,
                "summary": has_summary,
                "vector_db": has_vector_db
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 处理网页内容失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理网页内容失败: {str(e)}")


@router.get("/summary/{doc_name}")
async def get_web_summary(doc_name: str, summary_type: str = "brief"):
    """获取Web摘要 - 扫描目录查找任意 .md 文件"""
    try:
        import glob

        # Web 内容存储在 output/<doc_name>/ 目录下
        doc_output_dir = settings.data_dir / "output" / doc_name

        # 检查目录是否存在
        if not doc_output_dir.exists():
            # 检查是否使用了向量数据库（大文件模式）
            vector_db_path = settings.data_dir / "vector_db" / f"{doc_name}_vector_db"
            if vector_db_path.exists():
                return {
                    "status": "not_ready",
                    "message": f"该网页内容较大，已使用向量数据库存储，暂不支持摘要显示。请直接使用聊天功能进行问答。",
                    "content": "",
                    "is_large_file": True
                }
            else:
                return {
                    "status": "not_ready",
                    "message": f"文档目录不存在，请先处理网页内容",
                    "content": "",
                    "is_large_file": False
                }

        # 扫描目录下的所有 .md 文件
        md_files = list(doc_output_dir.glob("*.md"))

        if not md_files:
            return {
                "status": "not_ready",
                "message": f"摘要文件尚未生成，请等待处理完成",
                "content": "",
                "is_large_file": False
            }

        # 优先级匹配：根据 summary_type 选择文件
        summary_file = None

        if summary_type == "brief":
            # 优先查找 brief_summary.md 或 summary.md
            for pattern in ["brief_summary.md", "summary.md"]:
                for f in md_files:
                    if f.name == pattern:
                        summary_file = f
                        break
                if summary_file:
                    break
        else:
            # 查找 detail_summary.md
            for f in md_files:
                if f.name == "detail_summary.md":
                    summary_file = f
                    break

        # 如果没有找到匹配的，使用第一个 .md 文件
        if not summary_file and md_files:
            summary_file = md_files[0]
            logger.info(f"未找到特定摘要文件，使用第一个 .md 文件: {summary_file.name}")

        if not summary_file or not summary_file.exists():
            return {
                "status": "not_ready",
                "message": f"摘要文件不可用",
                "content": "",
                "is_large_file": False
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

        logger.info(f"✅ 成功加载Web摘要: {summary_file.name}")

        return {
            "status": "success",
            "summary_type": summary_type,
            "content": content,
            "file": str(summary_file),
            "file_name": summary_file.name
        }

    except Exception as e:
        logger.error(f"❌ 获取Web摘要失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取Web摘要失败: {str(e)}")


class WebInitializeRequest(BaseModel):
    url: Optional[str] = None


@router.post("/initialize/{doc_name}")
async def initialize_web_reader(
    doc_name: str, 
    request: WebInitializeRequest = Body(default=None)
):
    """初始化Web阅读器（用于聊天服务）"""
    try:
        # 提取 URL（如果提供）
        url = request.url if request and request.url else None

        # 🔥 向后兼容：检查多种可能的文件名格式
        json_data_dir = settings.data_dir / "json_data"
        json_path = json_data_dir / f"{doc_name}.json"
        
        # 如果标准文件名不存在，尝试查找包含特殊字符的旧文件名
        if not json_path.exists():
            logger.warning(f"标准文件名不存在: {json_path.name}")
            logger.info(f"🔍 尝试在 {json_data_dir} 中查找匹配的文件...")
            
            # 查找所有可能匹配的 JSON 文件
            if json_data_dir.exists():
                # 规范化 doc_name 用于比较
                doc_name_normalized = doc_name.replace(' ', '').lower()
                
                for candidate in json_data_dir.glob("*.json"):
                    # 规范化候选文件名用于比较
                    candidate_normalized = candidate.stem.replace(' ', '').lower()
                    
                    # 如果候选文件名以 doc_name 开头（忽略特殊字符）
                    if candidate_normalized.startswith(doc_name_normalized):
                        json_path = candidate
                        logger.info(f"✅ 找到匹配文件: {json_path.name}")
                        # 更新 doc_name 为实际文件名（不含扩展名）
                        doc_name = candidate.stem
                        break
        
        if not json_path.exists():
            logger.warning(f"⚠️ JSON数据文件不存在，无法初始化Web阅读器: {doc_name}")
            return {
                "status": "needs_processing",
                "message": f"Web内容 {doc_name} 需要重新处理",
                "doc_name": doc_name,
                "has_json": False
            }

        # 初始化聊天服务
        logger.info(f"🔄 正在初始化Web聊天服务: {doc_name}")
        logger.info(f"📊 初始化前ChatService状态: {chat_service.get_status()}")

        # 调用异步初始化方法
        success = await chat_service.initialize_web_reader(doc_name, url=url, provider="openai")

        logger.info(f"📊 初始化后ChatService状态: {chat_service.get_status()}")

        if success:
            logger.info(f"✅ Web阅读器和聊天服务初始化成功: {doc_name}")
            return {
                "status": "success",
                "message": f"Web阅读器已初始化: {doc_name}",
                "doc_name": doc_name,
                "has_json": True,
                "chat_initialized": True
            }
        else:
            logger.warning(f"⚠️ Web聊天服务初始化失败: {doc_name}")
            return {
                "status": "partial_success",
                "message": f"Web内容检查完成，但聊天服务初始化失败: {doc_name}",
                "doc_name": doc_name,
                "has_json": True,
                "chat_initialized": False
            }

    except Exception as e:
        logger.error(f"❌ 初始化Web阅读器失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"初始化Web阅读器失败: {str(e)}")