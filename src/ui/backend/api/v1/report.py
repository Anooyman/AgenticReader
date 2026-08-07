"""Report 数据 REST API——供前端拉取当天/历史论文与文章摘要卡片数据，
以及删除已处理条目。改自 ai-research-pipeline 的 webapp/api/report.py。
"""
from typing import Optional

from fastapi import APIRouter, HTTPException

from src.pipeline.paths import SUMMARIES_DIR
from src.pipeline.qa_labels import QA_LABELS
from src.ui.backend.services import report_data

router = APIRouter()


@router.get("/summaries")
async def get_summaries(coverage_date: Optional[str] = None):
    """coverage_date 省略时返回全部条目（保留旧行为，供未来"查看全部"
    场景使用）；传具体日期时只返回该天的内容，供 report 页面默认视图用。"""
    return report_data.load_all_summaries(coverage_date)


@router.get("/dates")
async def get_dates():
    return {"dates": report_data.list_coverage_dates()}


@router.get("/qa-labels")
async def get_qa_labels():
    return QA_LABELS


@router.get("/item/{item_id}/delete-preview")
async def get_delete_preview(item_id: str):
    """这个条目当前在哪几处有数据——确认框据此只列出真实存在的项，
    不让用户对着"memory 索引"打勾却其实这篇压根没写入过。"""
    return report_data.describe_delete_targets(item_id)


@router.post("/item/{item_id}/delete")
async def post_delete(item_id: str, body: dict = None):
    """删除条目在选定几处的数据。

    用 POST 而不是 DELETE：要带一个"删哪几处"的列表，DELETE 带 body 在
    各层代理/客户端里的支持一向不一致。
    """
    targets = (body or {}).get("targets") or []
    unknown = [t for t in targets if t not in report_data.VALID_DELETE_TARGETS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知的删除目标: {unknown}")
    if not targets:
        raise HTTPException(status_code=400, detail="targets 不能为空")
    return await report_data.delete_item(item_id, targets)
