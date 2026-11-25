"""后台任务查询/重试 API——供 briefs 页面轮询处理进度。"""
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


@router.delete("/{job_id}")
async def remove_job(job_id: str):
    """删除一条已结束的任务记录——失败/中断的任务不该在侧栏里长住。
    运行中的拒绝（400），要先走 cancel，避免"记录删了、活还在跑"。"""
    outcome = await job_runner.delete_job(job_id)
    if not outcome.get("ok"):
        raise HTTPException(status_code=400, detail=outcome.get("error", "删除失败"))
    return outcome
