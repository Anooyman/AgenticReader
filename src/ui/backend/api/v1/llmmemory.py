"""LLM-Memory 桥接 API——把外部 LLM-Memory webui（默认 http://127.0.0.1:8765）
的 brief 管线能力转发给本 UI 的记忆页面。

为什么用 HTTP 桥接而不是同进程 import：两边是各自独立演进的仓库/venv，
LLM-Memory 侧自己就有完整的 brief 抽取、增量状态、检索与对话链路；这里
只做透明代理，不做第二套语义——路由路径、参数、返回形状都尽量原样透传，
出问题时排查只看一层代码。

对话作用域约定：前端会把明确选择的日期拼进 query，并通过自然语言说明范围，
namespace 固定为 AATF。未选日期时保持原问题，不人为追加空范围提示。

例外：/load-jobs 不是透传，它把"加载某天的简报"登记进本仓库 job_runner 的
串行车道，再由 services/brief_memory.py 去驱动外部服务——外部那边没有队列
也没有并发上限，批量点日期时会失控，详见下面 /load-jobs 上方的说明。
"""
import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

LLM_MEMORY_URL = os.environ.get("LLM_MEMORY_URL", "http://127.0.0.1:8765").rstrip("/")
_TIMEOUT = httpx.Timeout(15.0, read=180.0)


async def _lm(method: str, path: str, **kw):
    """One hop to LLM-Memory webui; connection refused etc. become a clean
    502 naming both services instead of a raw traceback."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.request(method, f"{LLM_MEMORY_URL}{path}", **kw)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM-Memory webui 不可达（{LLM_MEMORY_URL}）：{exc}. "
                   f"请确认已运行: python scripts/webui/server.py --port 8765")
    if r.status_code >= 400:
        try:
            body = r.json()
        except ValueError:
            body = {"detail": r.text[:300]}
        raise HTTPException(status_code=r.status_code, detail=body)
    return r.json()


@router.get("/dates")
async def brief_dates():
    return await _lm("GET", "/api/briefs/dates")


@router.get("/papers")
async def brief_papers(request: Request):
    return await _lm("GET", "/api/briefs/papers",
                     params={"dates": request.query_params.get("dates", "")})


@router.post("/load")
async def brief_load(body: dict):
    return await _lm("POST", "/api/briefs/load",
                     json={"dates": (body or {}).get("dates") or []})


@router.get("/load/progress/{job_id}")
async def brief_load_progress(job_id: str):
    return await _lm("GET", f"/api/briefs/load/progress/{job_id}")


# ---- 队列驱动的批量加载 ----------------------------------------------------
# 上面那对 /load 是把请求原样转发给外部服务：那边是 thread-per-job，既没有
# 队列也没有并发上限（server.py 的 _MAX_ACTIVE_JOBS 只挂在 ingest/chat 上，
# brief load 一个都没接），日期列表上连点几行就会同时开好几个 job 一起打
# 同一个网关，同一日期并发跑两遍还会写进重复记忆行。
#
# 下面这组走 AgenticReader 自己的 job_runner 串行车道：一天一个 job，进度
# /取消/重试都是现成的（job 账本在 /api/v1/jobs 上，这里给了一份只含加载
# 任务的过滤视图）。原 /load 保留不动，仍然留给"一次塞多个日期"的用法。
#
# 取消语义有一点要留意：外部服务没有 brief load 的停止端点，取消本地 job
# 只是停止继续盯它，那一轮 load 还是会自己跑完——日期最终仍然会被加载上，
# 只是状态会先显示 cancelled 再在刷新后变回已加载。

_LOAD_KIND = "load_brief_date"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 单次请求最多排多少个日期。本地队列不设上限（串行本身就慢），这条只是
# 挡住误操作把整个月的日期一次塞进来。
_MAX_DATES_PER_REQUEST = 40


def _normalize_dates(body: dict) -> list:
    """接受 ["2026-10-13", ...] 或单个字符串，去重排序后校验格式。"""
    dates = (body or {}).get("dates")
    if isinstance(dates, str):
        dates = [dates]
    if not isinstance(dates, list) or not dates:
        raise HTTPException(status_code=400,
                            detail="dates: non-empty list of YYYY-MM-DD required")
    valid = sorted({d for d in dates if isinstance(d, str) and _DATE_RE.match(d)})
    if not valid:
        raise HTTPException(status_code=400,
                            detail="dates contains no valid YYYY-MM-DD entries")
    if len(valid) > _MAX_DATES_PER_REQUEST:
        raise HTTPException(status_code=400,
                            detail=f"一次最多排 {_MAX_DATES_PER_REQUEST} 个日期，请分批")
    return valid


@router.post("/load-jobs")
async def post_load_jobs(body: dict):
    """批量加载：每个日期登记一个后台任务，立刻返回，不等结果。

    `job_runner.enqueue()` 对同一个 target 会直接返回还在排队/运行的那条，
    所以重复点同一个日期不会跑两遍——这正是之前并发撞车的那个坑。"""
    from src.ui.backend.services import job_runner

    dates = _normalize_dates(body)
    jobs = [await job_runner.enqueue(_LOAD_KIND, d, title=f"加载简报 {d}")
            for d in dates]
    return {"requested": len(dates), "queued": len(jobs), "dates": dates, "jobs": jobs}


@router.get("/load-jobs")
async def get_load_jobs():
    """这个页专用的任务视图：只回 load_brief_date 类型，省得前端自己去
    /api/v1/jobs 里筛一遍。按创建时间倒序（job_runner.list_jobs 已排好）。"""
    from src.ui.backend.services import job_runner

    return {"jobs": [j for j in job_runner.list_jobs() if j.get("kind") == _LOAD_KIND]}


@router.post("/chat")
async def chat(body: dict):
    """Proxy of LM /api/chat (job-based). body: {message, history, namespace}.
    Namespace defaults to AATF because this page's whole premise is the
    brief pipeline."""
    payload = {
        "message": (body or {}).get("message") or "",
        "history": (body or {}).get("history") or [],
        "namespace": (body or {}).get("namespace") or ["AATF"],
    }
    if not payload["message"].strip():
        raise HTTPException(status_code=400, detail="message is required")
    return await _lm("POST", "/api/chat", json=payload)


@router.get("/chat/progress/{job_id}")
async def chat_progress(job_id: str):
    return await _lm("GET", f"/api/chat/progress/{job_id}")


@router.post("/download")
async def download(body: dict):
    """PDF → AgenticReader's data/pdf (the write happens on the LM side,
    whose deepread endpoint is configured to drop files right there)."""
    url = ((body or {}).get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    return await _lm("POST", "/api/deepread/download", json={"url": url})
