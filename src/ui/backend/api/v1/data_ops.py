"""数据管理 API——杂项运维域（REFACTOR_REPORT P2-4 拆分产物）

本模块负责 /data 页的任务类端点：待索引 PDF 的后台索引启动
（POST /documents/{filename}/index + 后台协程）与任务状态查询
（GET /tasks/{task_id}）。

文档产物清单/摘要/删除在 ``data.py``（documents 域）；存储类在
``data_storage.py``。URL 前缀 ``/api/v1/data`` 由 app.py 的 include_router
统一提供，本模块路由路径与拆分前逐条一致。
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pathlib import Path

from ...config import PDF_DIR
from src.core.document_management import DocumentRegistry
from ...services.task_service import task_manager

router = APIRouter()


# ==================== Helper Functions ====================

async def _index_pdf_background(task_id: str, filename: str, pdf_path: Path):
    """
    后台索引任务

    Args:
        task_id: 任务ID
        filename: PDF文件名
        pdf_path: PDF文件路径
    """
    try:
        from src.agents.indexing import IndexingAgent
        from .config import load_config

        doc_name_base = filename.replace('.pdf', '') if filename.endswith('.pdf') else filename

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

        print(f"🔄 后台索引任务开始: {filename} (task_id: {task_id})")

        # 进度回调：agent 只上报阶段，任务落库逻辑留在 UI 侧
        def _on_index_progress(stage: str, progress: int, message: str = "") -> None:
            stage_progress = {"start": 30, "graph": 40}.get(stage)
            if stage_progress is not None:
                task_manager.update_task(task_id, progress=stage_progress)

        # 执行索引（初始 state 由 IndexingAgent.index_document 统一构造）
        result = await indexing_agent.index_document(
            doc_name=doc_name_base,
            doc_path=str(pdf_path),
            doc_type="pdf",
            progress_callback=_on_index_progress,
        )

        task_manager.update_task(task_id, progress=90)

        if result.get("is_complete"):
            task_manager.complete_task(task_id, success=True)
            print(f"✅ 后台索引任务完成: {filename}")
        else:
            error_msg = result.get("error", "未知错误")
            task_manager.complete_task(task_id, success=False, error=error_msg)
            print(f"❌ 后台索引任务失败: {filename}, 错误: {error_msg}")

    except Exception as e:
        error_msg = str(e)
        task_manager.complete_task(task_id, success=False, error=error_msg)
        print(f"❌ 后台索引任务异常: {filename}, 错误: {error_msg}")
        import traceback
        traceback.print_exc()


# ==================== API Endpoints ====================

@router.post("/documents/{filename}/index")
async def index_pdf(filename: str, background_tasks: BackgroundTasks):
    """
    启动PDF索引后台任务

    Args:
        filename: PDF文件名
        background_tasks: FastAPI后台任务

    Returns:
        任务信息
    """
    try:
        # 检查PDF文件是否存在
        pdf_path = PDF_DIR / filename
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail=f"PDF文件不存在: {filename}")

        # 检查是否已经索引
        registry = DocumentRegistry()
        doc_name_base = filename.replace('.pdf', '') if filename.endswith('.pdf') else filename
        if registry.get_by_name(doc_name_base):
            raise HTTPException(status_code=400, detail=f"文档已索引: {filename}")

        # 创建后台任务
        task_id = task_manager.create_task(
            task_type="pdf_index",
            filename=filename,
            doc_name=doc_name_base
        )

        # 添加后台任务
        background_tasks.add_task(_index_pdf_background, task_id, filename, pdf_path)

        print(f"📋 索引任务已创建: {filename} (task_id: {task_id})")

        return {
            "status": "started",
            "task_id": task_id,
            "filename": filename,
            "message": f"索引任务已启动"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 创建索引任务失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """
    查询任务状态

    Args:
        task_id: 任务ID

    Returns:
        任务状态信息
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task
