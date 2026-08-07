"""后台任务查询/重试 API——供 briefs/report 页面轮询处理进度。"""
from fastapi import APIRouter, HTTPException

from src.ui.backend.services import job_runner

router = APIRouter()


@router.get("")
async def get_jobs():
    return {"jobs": job_runner.list_jobs()}


@router.post("/{job_id}/retry")
async def post_retry(job_id: str):
    outcome = await job_runner.retry_job(job_id)
    if not outcome.get("ok"):
        raise HTTPException(status_code=400, detail=outcome.get("error", "重试失败"))
    return outcome


@router.post("/{job_id}/cancel")
async def post_cancel(job_id: str):
    outcome = await job_runner.cancel_job(job_id)
    if not outcome.get("ok"):
        raise HTTPException(status_code=400, detail=outcome.get("error", "取消失败"))
    return outcome
