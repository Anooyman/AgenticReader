""" 章节管理 API"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from pydantic import BaseModel
import json
from pathlib import Path

from ...config import settings, get_logger
from .config import get_current_provider, get_current_pdf_preset
from src.core.processing.parallel_processor import ChapterProcessor

logger = get_logger(__name__)

router = APIRouter()


class ChapterInfo(BaseModel):
    """章节信息模型"""
    title: str
    pages: List[int]
    start_page: int
    end_page: int


class ChapterUpdate(BaseModel):
    """章节更新模型"""
    title: str
    pages: List[int]


@router.get("/documents/{doc_name}/chapters")
async def get_document_chapters(doc_name: str) -> Dict[str, Any]:
    """获取文档的章节信息
    
    Args:
        doc_name: 文档名称
        
    Returns:
        包含章节列表的字典
    """
    try:
        json_path = settings.data_dir / "json_data" / doc_name / "data.json"
        
        if not json_path.exists():
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_name}")
        
        # 读取JSON数据
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        if not isinstance(json_data, list):
            raise HTTPException(status_code=400, detail="文档格式不正确")
        
        # 优先从agenda缓存读取章节信息（用户可能已经修改）
        agenda_cache_path = settings.data_dir / "agenda" / f"{doc_name}_agenda.json"
        chapters = []
        chapter_dict = {}

        if agenda_cache_path.exists():
            # 从缓存读取
            try:
                with open(agenda_cache_path, 'r', encoding='utf-8') as f:
                    chapter_dict = json.load(f)
                
                for title, data in chapter_dict.items():
                    pages = data.get('pages', [])
                    if pages:
                        chapters.append({
                            "title": title,
                            "pages": pages,
                            "start_page": min(pages),
                            "end_page": max(pages),
                            "page_count": len(pages)
                        })
                logger.info(f"📚 从缓存加载了 {len(chapters)} 个章节")
            except Exception as cache_error:
                logger.warning(f"从缓存提取章节信息失败: {cache_error}")

        # 若无缓存，尝试读取本地结构文件（data/json_data/<doc>/structure.json）
        if not chapters:
            structure_path = settings.data_dir / "json_data" / doc_name / "structure.json"
            if structure_path.exists():
                try:
                    with open(structure_path, 'r', encoding='utf-8') as f:
                        structure_data = json.load(f)
                    agenda_dict = structure_data.get("agenda_dict", {}) if isinstance(structure_data, dict) else {}

                    for title, pages in agenda_dict.items():
                        if not pages:
                            continue
                        # 去重并排序，确保为整数页码
                        unique_pages = sorted({int(p) for p in pages if isinstance(p, (int, float, str))})
                        if not unique_pages:
                            continue
                        chapter_dict[title] = {"pages": unique_pages}
                        chapters.append({
                            "title": title,
                            "pages": unique_pages,
                            "start_page": min(unique_pages),
                            "end_page": max(unique_pages),
                            "page_count": len(unique_pages)
                        })

                    # 写入缓存，方便后续编辑
                    if chapters:
                        agenda_cache_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(agenda_cache_path, 'w', encoding='utf-8') as f:
                            json.dump(chapter_dict, f, ensure_ascii=False, indent=2)
                        logger.info(f"📁 读取本地结构文件并缓存 {len(chapters)} 个章节")
                except Exception as structure_error:
                    logger.warning(f"读取结构文件失败: {structure_error}")

        # 如果仍无章节信息，尝试从向量数据库读取
        if not chapters:
            vector_db_path = settings.data_dir / "vector_db" / f"{doc_name}_data_index"
            
            if vector_db_path.exists():
                # 从向量数据库元数据中提取章节信息
                try:
                    from langchain_community.vectorstores import FAISS
                    from src.core.llm.client import get_embeddings
                    
                    # 加载向量数据库
                    embeddings = get_embeddings()
                    vectorstore = FAISS.load_local(
                        str(vector_db_path),
                        embeddings,
                        allow_dangerous_deserialization=True
                    )
                    
                    # 从向量数据库文档中提取章节信息
                    docs = vectorstore.docstore._dict
                    
                    for doc_id, doc in docs.items():
                        metadata = doc.metadata
                        if metadata.get('type') == 'context':  # 只处理内容类型的文档
                            title = metadata.get('title', '未知章节')
                            pages = metadata.get('pages', [])
                            
                            if title and pages:
                                chapter_dict[title] = {
                                    'pages': pages,
                                    'data': metadata.get('raw_data', {})
                                }
                    
                    # 构建章节列表
                    for title, data in chapter_dict.items():
                        pages = data.get('pages', [])
                        if pages:
                            chapters.append({
                                "title": title,
                                "pages": pages,
                                "start_page": min(pages),
                                "end_page": max(pages),
                                "page_count": len(pages)
                            })
                    
                    # 保存到缓存以便后续修改（存储到agenda目录）
                    agenda_cache_path = settings.data_dir / "agenda" / f"{doc_name}_agenda.json"
                    agenda_cache_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(agenda_cache_path, 'w', encoding='utf-8') as f:
                        json.dump(chapter_dict, f, ensure_ascii=False, indent=2)
                    
                    logger.info(f"📚 从向量数据库加载了 {len(chapters)} 个章节并保存到缓存")
                        
                except Exception as e:
                    logger.warning(f"从向量数据库提取章节信息失败: {e}")
        
        # 如果没有章节信息，返回基于页码的默认结构
        if not chapters:
            total_pages = len(json_data)
            chapters = [{
                "title": f"完整文档",
                "pages": list(range(1, total_pages + 1)),
                "start_page": 1,
                "end_page": total_pages,
                "page_count": total_pages
            }]
            logger.info(f"📄 使用默认章节结构，共 {total_pages} 页")
        
        return {
            "success": True,
            "doc_name": doc_name,
            "total_chapters": len(chapters),
            "chapters": sorted(chapters, key=lambda x: x['start_page'])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文档章节失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))




@router.put("/documents/{doc_name}/chapters/{chapter_index}")
async def update_chapter(
    doc_name: str,
    chapter_index: int,
    chapter_data: ChapterUpdate
) -> Dict[str, str]:
    """更新章节信息（功能暂未实现）"""
    raise HTTPException(status_code=501, detail="章节修改功能暂未实现，请使用 IndexingAgent 重新索引文档")


@router.post("/documents/{doc_name}/chapters")
async def add_chapter(
    doc_name: str,
    chapter_data: ChapterUpdate
) -> Dict[str, str]:
    """添加新章节（功能暂未实现）"""
    raise HTTPException(status_code=501, detail="添加章节功能暂未实现，请使用 IndexingAgent 重新索引文档")


@router.delete("/documents/{doc_name}/chapters/{chapter_index}")
async def delete_chapter(
    doc_name: str,
    chapter_index: int
) -> Dict[str, str]:
    """删除章节（功能暂未实现）"""
    raise HTTPException(status_code=501, detail="删除章节功能暂未实现，请使用 IndexingAgent 重新索引文档")


@router.post("/documents/{doc_name}/rebuild")
async def rebuild_document_data(
    doc_name: str,
    rebuild_vectordb: bool = True,
    rebuild_summary: bool = False
) -> Dict[str, Any]:
    """重建文档数据（功能暂未实现）"""
    raise HTTPException(status_code=501, detail="重建功能暂未实现，请使用 IndexingAgent 重新索引文档")
