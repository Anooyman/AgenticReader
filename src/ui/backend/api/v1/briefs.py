"""简报浏览 REST API——每日简报的读取与按需加载。改自 ai-research-pipeline
的 webapp/api/briefs.py。

这一组接口让 WebUI 成为操作入口：先浏览、再挑感兴趣的加载，而不是像批
处理脚本那样一跑就是把当天全部条目都处理掉（十几篇 PDF 要四五个小时）。

GET 是纯读（解析 HTML，不写任何状态），POST 才会登记 queue 并派发后台
任务——任务本身由 job_runner 串行执行。
"""
from fastapi import APIRouter, HTTPException

from src.ui.backend.services import briefs_data, job_runner

router = APIRouter()


@router.get("/dates")
async def get_dates():
    return {"dates": briefs_data.available_dates()}


@router.get("/cards")
async def get_cards(coverage_date: str):
    return briefs_data.load_cards(coverage_date)


@router.post("/load")
async def post_load(body: dict):
    """把勾选的条目登记进 queue 并派发处理任务。

    每个条目一个任务，串行跑：下载 -> 索引 -> 多维度问答 -> 摘要 -> 入库。
    PDF 单篇 15-30 分钟，所以这里只负责入队，立刻返回，进度靠 /api/v1/jobs
    轮询。"""
    coverage_date = (body or {}).get("coverage_date")
    item_ids = (body or {}).get("item_ids") or []
    if not coverage_date:
        raise HTTPException(status_code=400, detail="coverage_date is required")
    if not item_ids:
        raise HTTPException(status_code=400, detail="item_ids is required")

    to_run = await briefs_data.register_for_processing(coverage_date, item_ids)
    jobs = [
        await job_runner.enqueue(
            "process_item", entry["item_id"],
            title=entry["title"], item_type=entry["type"],
        )
        for entry in to_run
    ]
    return {"requested": len(item_ids), "queued": len(jobs), "jobs": jobs}


@router.post("/render-report")
async def post_render_report(body: dict):
    coverage_date = (body or {}).get("coverage_date")
    if not coverage_date:
        raise HTTPException(status_code=400, detail="coverage_date is required")
    job = await job_runner.enqueue("render_report", coverage_date,
                                   title=f"生成 {coverage_date} 的报告")
    return {"job": job}


@router.post("/sync-memory")
async def post_sync_memory():
    """把所有还没入库的摘要补灌进 memory。

    正常路径下每篇处理完会自动入库，这个按钮是给历史欠账用的——比如
    memory 库被清空过、或早期处理的条目当时 inline ingest 失败了。"""
    job = await job_runner.enqueue("sync_memory", "__all_pending__",
                                   title="补灌全部未入库摘要")
    return {"job": job}
