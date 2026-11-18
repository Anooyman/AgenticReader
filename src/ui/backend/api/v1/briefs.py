"""简报浏览 REST API——每日简报的读取与按需加载。改自 ai-research-pipeline
的 webapp/api/briefs.py。

这一组接口让 WebUI 成为操作入口：先浏览、再挑感兴趣的加载，而不是像批
处理脚本那样一跑就是把当天全部条目都处理掉（十几篇 PDF 要四五个小时）。

GET 是纯读（解析 HTML，不写任何状态），POST 才会登记 queue 并派发后台
任务——任务本身由 job_runner 串行执行。
"""
import asyncio
import re

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.ui.backend.services import briefs_data, job_runner
from ...config import PDF_DIR

router = APIRouter()

# 轻量入库的日期参数——沿用原 /memory 页 /load-jobs 的 _normalize_dates
# 语义：dates 列表或单个串、格式校验、去重排序、跨日单次上限 40。
# 格式错误挡在入队之前，别让它晚一步在 job 里才炸出来。
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_DATES_PER_REQUEST = 40


def _normalize_dates(body: dict) -> list:
    """dates: [...] / "YYYY-MM-DD"，或旧参数 coverage_date 单值（兼容保留）。"""
    raw = (body or {}).get("dates")
    if raw is None:
        raw = (body or {}).get("coverage_date")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400,
                            detail="dates: 需要非空的 YYYY-MM-DD 日期列表（或 coverage_date 单值）")
    valid = sorted({d.strip() for d in raw if isinstance(d, str) and _DATE_RE.match(d.strip())})
    if not valid:
        raise HTTPException(status_code=400, detail="dates 中没有合法的 YYYY-MM-DD 条目")
    if len(valid) > _MAX_DATES_PER_REQUEST:
        raise HTTPException(status_code=400,
                            detail=f"一次最多排 {_MAX_DATES_PER_REQUEST} 个日期，请分批")
    return valid


@router.get("/memory-status")
async def get_memory_status():
    """各日期的真实入库计数：{"dates": {"2026-11-12": {"aatf": 37, "heavy_done": 2}, ...}}

    供 /briefs 页区分"有 HTML 未入库 / 有 HTML 已入库 / 无 HTML"三种状态
    （无 HTML 的日期根本不会出现在列表里）。数据来源是 A 自库行 + queue
    事实，**不是任务账本**——bridge 时代的 done ≠ A 自库有数据，按账本
    显示只会造出满屏"已入库"的假象（state-auditor 审计实锤）。
    纯读，LanceDB 全行扫描是函数级 to_thread，不阻塞事件循环。"""
    counts = await asyncio.to_thread(briefs_data.date_memory_counts)
    return {"dates": counts}


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


@router.post("/sync-memory")
async def post_sync_memory():
    """把所有还没入库的摘要补灌进 memory。

    正常路径下每篇处理完会自动入库，这个按钮是给历史欠账用的——比如
    memory 库被清空过、或早期处理的条目当时 inline ingest 失败了。"""
    job = await job_runner.enqueue("sync_memory", "__all_pending__",
                                   title="补灌全部未入库摘要")
    return {"job": job}


@router.post("/light-load")
async def post_light_load(body: dict):
    """轻量入库：这一天的简报卡片直接写进 A 自库 memory 的 namespace
    AATF，走 load_brief_date 任务——不下载 PDF、不做多维问答，零 LLM
    调用，一天几秒到几十秒就完事。

    与 /load 的分工（取代原 /memory 页的日期加载）：
      /load        重管线，条目级，产摘要 + 入 ai-research；
      /light-load  轻量级，日期级，卡片导读原文直接入 AATF。
    驱动分派在 gateway.load_brief_date（缺省 local；env
    MEMORY_BRIEF_DRIVER=bridge 时回到外部 LLM-Memory 桥，仅作兜底）。

    日期参数：{dates: [...]} 一次给多天（沿用原 /load-jobs 的批量语义），
    或 {coverage_date: "YYYY-MM-DD"} 单日兼容旧调用。逐日一个
    load_brief_date job——job_runner 对同一 target 直接返回在飞的旧 job，
    重复点同一个日期不会跑两遍。"""
    dates = _normalize_dates(body)
    jobs = [await job_runner.enqueue("load_brief_date", d, title=f"轻量入库 {d}")
            for d in dates]
    return {"requested": len(dates), "queued": len(jobs),
            "dates": dates, "jobs": jobs}


# ---- 论文"下载入库"：把卡片 PDF 拉进 data/pdf 并触发本地索引 --------------
# 原 /memory 页对话回复里「⬇下载入库」能力的本地化替身——旧实现靠 B 侧
# deepread 端点下载，本地库路线下这一步必须自己完成：下载→落 data/pdf→
# 复用 documents.py 的同一条 IndexingAgent 后台流。
_FETCH_PDF_MAX_BYTES = 100 * 1024 * 1024
_NAME_SAFE_RE = re.compile(r"^[\w][\w.+ -]*$", re.UNICODE)
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})(?:v\d+)?(?:[.#][^/?]*)?(?:[?#].*)?$",
                           re.IGNORECASE)


def _pdf_doc_name_from_url(url: str) -> str:
    """从 URL 推 PDF 的入库文档名（不带 .pdf 后缀）。

    arXiv 优先：id 走 briefs_parser.arxiv_id_no_version——与重管线
    process_pdf_queue 的 doc_name=item_id 约定同源，同一个条目在重管线
    和这里入的库指向同一个文档名，registry 不裂。非 arXiv 取路径末段
    消毒；认不出返回空串，由调用方 400。
    """
    m = _ARXIV_URL_RE.search(url)
    if m:
        from src.pipeline.briefs_parser import arxiv_id_no_version
        return arxiv_id_no_version(m.group(1))
    from urllib.parse import urlparse, unquote
    last = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    last = unquote(last)
    if last.lower().endswith(".pdf"):
        last = last[:-4]
    if not last or not _NAME_SAFE_RE.match(last):
        return ""
    return last


@router.post("/fetch-pdf")
async def post_fetch_pdf(body: dict, background_tasks: BackgroundTasks):
    """下载论文 PDF 到 data/pdf/ 并启动索引，返回 {doc_name, status, indexed?}。

    - status="exists"：文件已在 data/pdf（不重复下载，直接可索引/深读）
    - status="started"：刚下载完，索引已进后台任务流
    - 下载校验 %PDF- 魔数 + 100MB 上限；redirects 跟随（arxiv 常见）
    """
    url = ((body or {}).get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url 必须是 http(s) 链接")
    doc_base = _pdf_doc_name_from_url(url)
    if not doc_base:
        raise HTTPException(status_code=400, detail="URL 推不出安全的 PDF 文件名")

    target = PDF_DIR / f"{doc_base}.pdf"
    if target.exists():
        # 已在库——可能已索引，交给前端查 documents 列表决定显示状态
        return {"status": "exists", "doc_name": target.name}

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(target.name + ".part")
    downloaded = 0
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0),
                                     headers={"User-Agent": "Mozilla/5.0 (AgenticReader brief fetch)"}) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise HTTPException(status_code=502,
                                        detail=f"下载失败：HTTP {resp.status_code}")
                first = True
                with tmp_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(1 << 16):
                        if first:
                            if not chunk.startswith(b"%PDF-"):
                                raise HTTPException(status_code=400, detail="目标不是有效的 PDF 文件")
                            first = False
                        downloaded += len(chunk)
                        if downloaded > _FETCH_PDF_MAX_BYTES:
                            raise HTTPException(status_code=413, detail="PDF 超过 100MB 上限")
                        f.write(chunk)
        tmp_path.replace(target)
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    except httpx.HTTPError as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"下载失败：{exc}") from exc
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(e))

    from src.ui.backend.api.v1.documents import _index_document_task
    background_tasks.add_task(_index_document_task, doc_name=target.name,
                              provider=None, pdf_preset="high")
    return {"status": "started", "doc_name": target.name}
