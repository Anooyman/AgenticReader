"""文档结构管理 API"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Any, List
from pydantic import BaseModel
import json
from pathlib import Path

from ...config import JSON_DATA_DIR, PDF_DIR, DATA_DIR
from src.utils.path_guard import safe_path
from ...services.task_service import task_manager

router = APIRouter()


class StructureUpdate(BaseModel):
    """结构更新模型"""
    agenda_dict: Dict[str, List[int]]  # {章节标题: [页码列表]}
    has_toc: bool = False


@router.get("/{doc_name}")
async def get_structure(doc_name: str) -> Dict[str, Any]:
    """
    获取文档的结构信息

    Args:
        doc_name: 文档名称

    Returns:
        structure.json 内容
    """
    try:
        # Strip .pdf extension if present to get base name for folder lookup
        # 目录穿越防护
        try:
            safe_path(DATA_DIR, doc_name)
        except ValueError as guard_e:
            raise HTTPException(status_code=400, detail=f"非法文档名: {guard_e}")

        doc_name_base = doc_name.replace('.pdf', '') if doc_name.endswith('.pdf') else doc_name

        # 构建 structure.json 路径
        structure_path = JSON_DATA_DIR / doc_name_base / "structure.json"

        if not structure_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"结构文件不存在: {doc_name}"
            )

        # 读取 structure.json
        with open(structure_path, 'r', encoding='utf-8') as f:
            structure_data = json.load(f)

        # 兼容新旧格式
        if isinstance(structure_data, dict):
            if "agenda_dict" in structure_data:
                # 新格式
                agenda_dict = structure_data.get("agenda_dict", {})
                has_toc = structure_data.get("has_toc", False)
            else:
                # 旧格式：整个文件就是 agenda_dict
                agenda_dict = structure_data
                has_toc = True
        else:
            raise HTTPException(
                status_code=400,
                detail="结构文件格式错误"
            )

        # 同时读取 PDF 数据以获取总页数
        data_path = JSON_DATA_DIR / doc_name_base / "data.json"
        total_pages = 0
        if data_path.exists():
            with open(data_path, 'r', encoding='utf-8') as f:
                pdf_data = json.load(f)
                if isinstance(pdf_data, list):
                    total_pages = len(pdf_data)

        print(f"✅ 获取结构成功: {doc_name}, {len(agenda_dict)} 个章节")

        return {
            "success": True,
            "doc_name": doc_name,
            "agenda_dict": agenda_dict,
            "has_toc": has_toc,
            "total_pages": total_pages,
            "total_chapters": len(agenda_dict)
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 获取结构失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{doc_name}")
async def update_structure(
    doc_name: str,
    structure: StructureUpdate
) -> Dict[str, Any]:
    """
    更新文档的结构信息

    Args:
        doc_name: 文档名称
        structure: 新的结构数据

    Returns:
        更新结果
    """
    try:
        # Strip .pdf extension if present to get base name for folder lookup
        # 目录穿越防护
        try:
            safe_path(DATA_DIR, doc_name)
        except ValueError as guard_e:
            raise HTTPException(status_code=400, detail=f"非法文档名: {guard_e}")

        doc_name_base = doc_name.replace('.pdf', '') if doc_name.endswith('.pdf') else doc_name

        # 构建路径
        doc_json_folder = JSON_DATA_DIR / doc_name_base
        structure_path = doc_json_folder / "structure.json"

        if not doc_json_folder.exists():
            raise HTTPException(
                status_code=404,
                detail=f"文档数据目录不存在: {doc_name}"
            )

        # 验证页码范围
        data_path = doc_json_folder / "data.json"
        if data_path.exists():
            with open(data_path, 'r', encoding='utf-8') as f:
                pdf_data = json.load(f)
                if isinstance(pdf_data, list):
                    max_page = len(pdf_data)

                    # 检查所有章节的页码是否在有效范围内
                    for title, pages in structure.agenda_dict.items():
                        for page in pages:
                            if page < 1 or page > max_page:
                                raise HTTPException(
                                    status_code=400,
                                    detail=f"章节 '{title}' 的页码 {page} 超出范围 (1-{max_page})"
                                )

        # 保存新的结构
        structure_data = {
            "agenda_dict": structure.agenda_dict,
            "has_toc": structure.has_toc
        }

        with open(structure_path, 'w', encoding='utf-8') as f:
            json.dump(structure_data, f, ensure_ascii=False, indent=2)

        print(f"✅ 结构更新成功: {doc_name}, {len(structure.agenda_dict)} 个章节")

        return {
            "success": True,
            "message": "结构更新成功",
            "doc_name": doc_name,
            "total_chapters": len(structure.agenda_dict)
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 更新结构失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _rebuild_background(task_id: str, doc_name: str, pdf_path: Path):
    """
    后台重建任务

    Args:
        task_id: 任务ID
        doc_name: 文档名称（不带.pdf后缀）
        pdf_path: PDF文件路径
    """
    try:
        from src.agents.indexing import IndexingAgent
        from .config import load_config

        # 更新任务进度
        task_manager.update_task(task_id, progress=10, status="running")

        # 从配置加载 provider 和 pdf_preset
        config = load_config()
        provider = config.get("provider", "openai")
        pdf_preset = config.get("pdf_preset", "high")
        print(f"📌 使用配置: provider={provider}, pdf_preset={pdf_preset}")

        # 创建索引agent
        indexing_agent = IndexingAgent(provider=provider, pdf_preset=pdf_preset)
        task_manager.update_task(task_id, progress=20)

        print(f"🔄 后台重建任务开始: {doc_name} (task_id: {task_id})")

        # 执行重建
        result = await indexing_agent.rebuild_from_structure(
            doc_name=doc_name,
            doc_path=str(pdf_path)
        )

        task_manager.update_task(task_id, progress=90)

        if result.get("success"):
            task_manager.complete_task(task_id, success=True)
            print(f"✅ 后台重建任务完成: {doc_name}")
        else:
            error_msg = result.get("error", "未知错误")
            task_manager.complete_task(task_id, success=False, error=error_msg)
            print(f"❌ 后台重建任务失败: {doc_name}, 错误: {error_msg}")

    except Exception as e:
        error_msg = str(e)
        task_manager.complete_task(task_id, success=False, error=error_msg)
        print(f"❌ 后台重建任务异常: {doc_name}, 错误: {error_msg}")
        import traceback
        traceback.print_exc()


@router.post("/{doc_name}/rebuild")
async def rebuild_from_structure(
    doc_name: str,
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """
    基于更新后的 structure 启动后台重建任务

    保持不变的文件：
    - structure.json: 手动编辑的结构
    - data.json: PDF 原始数据
    - pdf_image/: PDF 图片文件

    重新生成的内容：
    - chunks.json: 章节数据
    - 章节摘要: 所有章节的摘要和重构内容
    - 向量数据库: FAISS 索引
    - 简要摘要: 整体文档摘要

    Args:
        doc_name: 文档名称
        background_tasks: FastAPI后台任务

    Returns:
        任务信息
    """
    try:
        # Strip .pdf extension if present to get base name for folder lookup
        # 目录穿越防护
        try:
            safe_path(DATA_DIR, doc_name)
        except ValueError as guard_e:
            raise HTTPException(status_code=400, detail=f"非法文档名: {guard_e}")

        doc_name_base = doc_name.replace('.pdf', '') if doc_name.endswith('.pdf') else doc_name

        # 验证文档存在
        structure_path = JSON_DATA_DIR / doc_name_base / "structure.json"
        if not structure_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"结构文件不存在: {doc_name}"
            )

        # 获取文档路径
        pdf_path = PDF_DIR / f"{doc_name_base}.pdf"
        if not pdf_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"PDF 文件不存在: {doc_name}.pdf"
            )

        # 创建后台任务
        task_id = task_manager.create_task(
            task_type="structure_rebuild",
            filename=f"{doc_name_base}.pdf",
            doc_name=doc_name_base
        )

        # 添加后台任务
        background_tasks.add_task(_rebuild_background, task_id, doc_name_base, pdf_path)

        print(f"📋 重建任务已创建: {doc_name} (task_id: {task_id})")

        return {
            "success": True,
            "status": "started",
            "task_id": task_id,
            "doc_name": doc_name,
            "message": f"重建任务已启动，将在后台执行"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 创建重建任务失败: {e}")
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{doc_name}/chapter/{chapter_title}")
async def delete_chapter(
    doc_name: str,
    chapter_title: str
) -> Dict[str, Any]:
    """
    删除指定章节

    Args:
        doc_name: 文档名称
        chapter_title: 章节标题

    Returns:
        删除结果
    """
    try:
        # Strip .pdf extension if present to get base name for folder lookup
        # 目录穿越防护
        try:
            safe_path(DATA_DIR, doc_name)
        except ValueError as guard_e:
            raise HTTPException(status_code=400, detail=f"非法文档名: {guard_e}")

        doc_name_base = doc_name.replace('.pdf', '') if doc_name.endswith('.pdf') else doc_name

        # 读取当前结构
        structure_path = JSON_DATA_DIR / doc_name_base / "structure.json"

        if not structure_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"结构文件不存在: {doc_name}"
            )

        with open(structure_path, 'r', encoding='utf-8') as f:
            structure_data = json.load(f)

        # 兼容格式
        if "agenda_dict" in structure_data:
            agenda_dict = structure_data["agenda_dict"]
            has_toc = structure_data.get("has_toc", False)
        else:
            agenda_dict = structure_data
            has_toc = True

        # 删除章节
        if chapter_title not in agenda_dict:
            raise HTTPException(
                status_code=404,
                detail=f"章节不存在: {chapter_title}"
            )

        del agenda_dict[chapter_title]

        # 保存
        new_structure = {
            "agenda_dict": agenda_dict,
            "has_toc": has_toc
        }

        with open(structure_path, 'w', encoding='utf-8') as f:
            json.dump(new_structure, f, ensure_ascii=False, indent=2)

        print(f"✅ 章节删除成功: {chapter_title}")

        return {
            "success": True,
            "message": f"章节 '{chapter_title}' 已删除",
            "remaining_chapters": len(agenda_dict)
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 删除章节失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
