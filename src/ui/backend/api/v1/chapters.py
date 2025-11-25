"""章节管理 API"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from pydantic import BaseModel
import json
from pathlib import Path

from ...config import settings, get_logger

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
        json_path = settings.data_dir / "json_data" / f"{doc_name}.json"
        
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
        
        # 如果缓存不存在，尝试从向量数据库读取
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
) -> Dict[str, Any]:
    """更新指定章节的信息
    
    Args:
        doc_name: 文档名称
        chapter_index: 章节索引
        chapter_data: 更新的章节数据
        
    Returns:
        更新结果
    """
    try:
        json_path = settings.data_dir / "json_data" / f"{doc_name}.json"
        
        if not json_path.exists():
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_name}")
        
        # 读取JSON数据验证
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        total_pages = len(json_data)
        
        # 验证页码范围
        if not all(1 <= page <= total_pages for page in chapter_data.pages):
            raise HTTPException(
                status_code=400, 
                detail=f"页码超出范围 (1-{total_pages})"
            )
        
        # 尝试更新PDF阅读器中的章节信息
        try:
            from src.readers.pdf import PDFReader
            
            # 加载现有的章节信息
            agenda_cache_path = settings.data_dir / "agenda" / f"{doc_name}_agenda.json"
            
            if agenda_cache_path.exists():
                with open(agenda_cache_path, 'r', encoding='utf-8') as f:
                    agenda_dict = json.load(f)
                
                # 按照 start_page 排序章节（与 GET 请求保持一致）
                sorted_chapters = []
                for title, data in agenda_dict.items():
                    pages = data.get('pages', [])
                    if pages:
                        sorted_chapters.append({
                            'title': title,
                            'start_page': min(pages)
                        })
                sorted_chapters.sort(key=lambda x: x['start_page'])
                
                if 0 <= chapter_index < len(sorted_chapters):
                    old_title = sorted_chapters[chapter_index]['title']
                    
                    # 如果标题改变，需要重新创建条目
                    if chapter_data.title != old_title:
                        # 保存旧数据
                        old_data = agenda_dict.pop(old_title)
                        # 创建新条目
                        agenda_dict[chapter_data.title] = {
                            'pages': chapter_data.pages,
                            'data': old_data.get('data', {})
                        }
                    else:
                        # 只更新页码
                        agenda_dict[old_title]['pages'] = chapter_data.pages
                    
                    # 保存更新后的数据
                    with open(agenda_cache_path, 'w', encoding='utf-8') as f:
                        json.dump(agenda_dict, f, ensure_ascii=False, indent=2)
                    
                    logger.info(f"✅ 章节 {chapter_index} 已更新: {chapter_data.title}")
                    
                    return {
                        "success": True,
                        "message": f"章节已更新: {chapter_data.title}",
                        "chapter": {
                            "title": chapter_data.title,
                            "pages": chapter_data.pages,
                            "start_page": min(chapter_data.pages),
                            "end_page": max(chapter_data.pages)
                        }
                    }
                else:
                    raise HTTPException(status_code=404, detail="章节索引超出范围")
            else:
                # 如果缓存不存在，创建新的
                logger.info(f"创建新的agenda缓存: {doc_name}")
                agenda_dict = {
                    chapter_data.title: {
                        'pages': chapter_data.pages,
                        'data': {}
                    }
                }
                
                # 保存到文件
                agenda_cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(agenda_cache_path, 'w', encoding='utf-8') as f:
                    json.dump(agenda_dict, f, ensure_ascii=False, indent=2)
                
                return {
                    "success": True,
                    "message": f"章节已创建: {chapter_data.title}",
                    "chapter": {
                        "title": chapter_data.title,
                        "pages": chapter_data.pages,
                        "start_page": min(chapter_data.pages),
                        "end_page": max(chapter_data.pages)
                    }
                }
                
        except Exception as e:
            logger.error(f"更新章节失败: {e}")
            raise HTTPException(status_code=500, detail=f"更新章节失败: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新章节失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/{doc_name}/chapters")
async def add_chapter(
    doc_name: str,
    chapter_data: ChapterUpdate
) -> Dict[str, Any]:
    """添加新章节
    
    Args:
        doc_name: 文档名称
        chapter_data: 新章节数据
        
    Returns:
        添加结果
    """
    try:
        json_path = settings.data_dir / "json_data" / f"{doc_name}.json"
        
        if not json_path.exists():
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_name}")
        
        # 验证页码
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        total_pages = len(json_data)
        if not all(1 <= page <= total_pages for page in chapter_data.pages):
            raise HTTPException(
                status_code=400,
                detail=f"页码超出范围 (1-{total_pages})"
            )
        
        # 加载或创建agenda缓存
        agenda_cache_path = settings.data_dir / "agenda" / f"{doc_name}_agenda.json"
        
        if agenda_cache_path.exists():
            with open(agenda_cache_path, 'r', encoding='utf-8') as f:
                agenda_dict = json.load(f)
        else:
            agenda_dict = {}
            agenda_cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 检查章节标题是否已存在
        if chapter_data.title in agenda_dict:
            raise HTTPException(
                status_code=400,
                detail=f"章节标题已存在: {chapter_data.title}"
            )
        
        # 添加新章节
        agenda_dict[chapter_data.title] = {
            'pages': chapter_data.pages,
            'data': {}
        }
        
        # 保存更新后的数据
        with open(agenda_cache_path, 'w', encoding='utf-8') as f:
            json.dump(agenda_dict, f, ensure_ascii=False, indent=2)
        
        logger.info(f"📝 添加新章节: {chapter_data.title} (页码: {chapter_data.pages})")
        
        return {
            "success": True,
            "message": f"章节已添加: {chapter_data.title}",
            "chapter": {
                "title": chapter_data.title,
                "pages": chapter_data.pages,
                "start_page": min(chapter_data.pages),
                "end_page": max(chapter_data.pages)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加章节失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{doc_name}/chapters/{chapter_index}")
async def delete_chapter(
    doc_name: str,
    chapter_index: int
) -> Dict[str, Any]:
    """删除指定章节
    
    Args:
        doc_name: 文档名称
        chapter_index: 章节索引
        
    Returns:
        删除结果
    """
    try:
        agenda_cache_path = settings.data_dir / "agenda" / f"{doc_name}_agenda.json"
        
        if not agenda_cache_path.exists():
            raise HTTPException(status_code=404, detail=f"文档章节缓存不存在: {doc_name}")
        
        # 读取现有章节
        with open(agenda_cache_path, 'r', encoding='utf-8') as f:
            agenda_dict = json.load(f)
        
        # 按照 start_page 排序章节（与 GET 请求保持一致）
        sorted_chapters = []
        for title, data in agenda_dict.items():
            pages = data.get('pages', [])
            if pages:
                sorted_chapters.append({
                    'title': title,
                    'start_page': min(pages)
                })
        sorted_chapters.sort(key=lambda x: x['start_page'])
        
        if not (0 <= chapter_index < len(sorted_chapters)):
            raise HTTPException(status_code=404, detail="章节索引超出范围")
        
        # 获取要删除的章节标题（使用排序后的索引）
        chapter_title = sorted_chapters[chapter_index]['title']
        
        # 删除章节
        del agenda_dict[chapter_title]
        
        # 保存更新后的数据
        with open(agenda_cache_path, 'w', encoding='utf-8') as f:
            json.dump(agenda_dict, f, ensure_ascii=False, indent=2)
        
        logger.info(f"🗑️ 删除章节: {chapter_title} (索引: {chapter_index})")
        
        return {
            "success": True,
            "message": f"章节已删除: {chapter_title}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除章节失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/{doc_name}/rebuild")
async def rebuild_document_data(
    doc_name: str,
    rebuild_vectordb: bool = True,
    rebuild_summary: bool = True
) -> Dict[str, Any]:
    """根据修改后的章节信息重建向量数据库和摘要
    
    Args:
        doc_name: 文档名称
        rebuild_vectordb: 是否重建向量数据库
        rebuild_summary: 是否重建摘要
        
    Returns:
        重建结果
    """
    try:
        from src.readers.pdf import PDFReader
        from langchain.docstore.document import Document
        
        logger.info(f"🔄 开始重建文档数据: {doc_name}")
        logger.info(f"  - 重建向量数据库: {rebuild_vectordb}")
        logger.info(f"  - 重建摘要: {rebuild_summary}")
        
        # 检查文档是否存在
        json_path = settings.data_dir / "json_data" / f"{doc_name}.json"
        if not json_path.exists():
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_name}")
        
        # 读取JSON数据
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data_list = json.load(f)
        
        # 转换为字典格式 {page: data}
        json_data_dict = {int(item['page']): item.get('data', '') for item in json_data_list}
        
        # 读取修改后的章节信息
        agenda_cache_path = settings.data_dir / "agenda" / f"{doc_name}_agenda.json"
        if not agenda_cache_path.exists():
            raise HTTPException(status_code=400, detail="章节信息缓存不存在，请先编辑章节")
        
        with open(agenda_cache_path, 'r', encoding='utf-8') as f:
            agenda_dict_unsorted = json.load(f)
        
        # 按照起始页码排序agenda_dict，确保输出顺序正确
        sorted_items = sorted(
            agenda_dict_unsorted.items(),
            key=lambda x: min(x[1].get('pages', [float('inf')]))
        )
        agenda_dict = dict(sorted_items)
        
        # 将排序后的agenda保存回文件
        with open(agenda_cache_path, 'w', encoding='utf-8') as f:
            json.dump(agenda_dict, f, ensure_ascii=False, indent=2)
        logger.info(f"📋 章节已按页码排序，共 {len(agenda_dict)} 个章节")
        
        # 初始化PDF阅读器
        pdf_reader = PDFReader(provider="openai")
        pdf_reader.agenda_dict = agenda_dict
        pdf_reader.output_path = settings.data_dir / "output" / doc_name
        pdf_reader.output_path.mkdir(parents=True, exist_ok=True)
        
        rebuild_results = {}
        
        # 重建向量数据库
        if rebuild_vectordb:
            logger.info("📊 开始重建向量数据库...")
            try:
                vector_db_content_docs = []
                total_summary = {}
                
                for title, chapter_info in agenda_dict.items():
                    pages = chapter_info.get('pages', [])
                    # 从JSON数据中提取该章节的原始数据
                    raw_data = {page: json_data_dict.get(page, '') for page in pages if page in json_data_dict}
                    
                    # 生成章节内容和摘要
                    logger.info(f"  - 处理章节: {title} (页码: {min(pages)}-{max(pages)})")
                    content_list = [raw_data[page] for page in sorted(raw_data.keys()) if raw_data.get(page)]
                    
                    if not content_list:
                        logger.warning(f"  ⚠️ 章节 '{title}' 没有内容，跳过")
                        continue
                    
                    summary = pdf_reader.summary_content(title, content_list)
                    refactor = pdf_reader.refactor_content(title, content_list)
                    total_summary[title] = summary
                    
                    # 构建向量数据库文档
                    vector_db_content_docs.append(
                        Document(
                            page_content=summary,
                            metadata={
                                "type": "context",
                                "title": title,
                                "pages": pages,
                                "raw_data": raw_data,
                                "refactor": refactor,
                            }
                        )
                    )
                    vector_db_content_docs.append(
                        Document(
                            page_content=title,
                            metadata={
                                "type": "title",
                                "pages": pages,
                                "summary": summary,
                                "raw_data": raw_data,
                                "refactor": refactor,
                            }
                        )
                    )
                
                # 保存总摘要到PDF阅读器
                pdf_reader.total_summary = total_summary
                
                # 初始化向量数据库客户端（修正参数名）
                from src.core.vector_db.vector_db_client import VectorDBClient
                vector_db_path = str(settings.data_dir / "vector_db" / f"{doc_name}_data_index")
                vector_db_client = VectorDBClient(db_path=vector_db_path, provider="openai")
                
                # 重建向量数据库
                logger.info(f"  - 开始构建向量数据库，共 {len(vector_db_content_docs)} 个文档")
                vector_db_client.build_vector_db(vector_db_content_docs)
                
                rebuild_results['vectordb'] = {
                    'success': True,
                    'chapters_processed': len([t for t in agenda_dict.keys()]),
                    'documents_created': len(vector_db_content_docs)
                }
                logger.info(f"✅ 向量数据库重建完成")
                
            except Exception as e:
                logger.error(f"❌ 向量数据库重建失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
                rebuild_results['vectordb'] = {
                    'success': False,
                    'error': str(e)
                }
        
        # 重建摘要文件
        if rebuild_summary:
            logger.info("📝 开始重建摘要文件...")
            try:
                # 如果在重建向量数据库时已经生成了摘要，直接使用
                if not hasattr(pdf_reader, 'total_summary') or not pdf_reader.total_summary:
                    logger.info("  - 重新生成章节摘要")
                    total_summary = {}
                    for title, chapter_info in agenda_dict.items():
                        pages = chapter_info.get('pages', [])
                        raw_data = {page: json_data_dict.get(page, '') for page in pages if page in json_data_dict}
                        content_list = [raw_data[page] for page in sorted(raw_data.keys()) if raw_data.get(page)]
                        
                        if not content_list:
                            continue
                        
                        summary = pdf_reader.summary_content(title, content_list)
                        total_summary[title] = summary
                    
                    pdf_reader.total_summary = total_summary
                
                # 设置raw_data_dict用于详细摘要
                pdf_reader.raw_data_dict = {}
                for title, chapter_info in agenda_dict.items():
                    pages = chapter_info.get('pages', [])
                    raw_data = {page: json_data_dict.get(page, '') for page in pages if page in json_data_dict}
                    if raw_data:
                        pdf_reader.raw_data_dict[title] = raw_data
                
                logger.info(f"  - 生成简要摘要 (brief_summary.md)")
                # 生成简要摘要
                pdf_reader.get_brief_summary(file_type_list=["md"])
                
                logger.info(f"  - 生成详细摘要 (detail_summary.md)")
                # 生成详细摘要 - 传入raw_data_dict格式: {title: {page: content}}
                pdf_reader.get_detail_summary(pdf_reader.raw_data_dict, file_type_list=["md"])
                
                rebuild_results['summary'] = {
                    'success': True,
                    'output_path': str(pdf_reader.output_path),
                    'files_generated': ['brief_summary.md', 'detail_summary.md']
                }
                logger.info(f"✅ 摘要文件重建完成，保存到: {pdf_reader.output_path}")
                
            except Exception as e:
                logger.error(f"❌ 摘要文件重建失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
                rebuild_results['summary'] = {
                    'success': False,
                    'error': str(e)
                }
        
        return {
            "success": True,
            "message": "文档数据重建完成",
            "doc_name": doc_name,
            "results": rebuild_results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重建文档数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
