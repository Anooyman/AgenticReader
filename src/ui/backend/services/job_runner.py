"""后台任务车道——把耗时的 pipeline 操作从 HTTP 请求里挪出去。

改自 ai-research-pipeline 的 webapp/services/job_runner.py。

## 为什么需要它

处理一篇 PDF 要 15-30 分钟（下载 -> IndexingAgent 索引 -> 六维度问答 ->
生成摘要 -> 写入 memory），web 文章几分钟。这不可能放在请求里同步等，必须
后台跑、前端轮询进度。

## 只有一条车道

这里管的是会写 pipeline_queue.json 的那类任务，必须串行——queue 是整
文件读写，两个任务同时改会互相覆盖（queue_store.queue_transaction 的锁
保证单次读改写原子，但让两个长任务交错跑仍然没有意义：它们最终都要改
同一批条目的状态）。

对话入库是另一条独立车道（src/ui/backend/services/chat_ingest.py 自己的
worker），刻意不放进这里：它只写 memory、不碰 queue，没有串行必要，而且
挤在同一条队列里会被一个 30 分钟的 PDF 任务堵死。

## 直接函数调用，不是 subprocess

原 ai-research-pipeline 实现里，process_pdf_queue.py/process_web_queue.py
是通过 subprocess 用 AgenticReader 的 venv 跑的——因为当时两个仓库不在
同一个 Python 进程里（webapp 主进程要保持轻量）。合并进 AgenticReader
后，这些脚本的 main_async() 就是普通函数，直接 await 调用即可。

**这也意味着丢掉了 subprocess 天然带来的超时保护（进程被 kill）**——
原实现的 TIMEOUTS 字典本来是传给 subprocess_util.run_subprocess() 用的，
这里改用 asyncio.wait_for() 包一层，效果等价：超时即抛
asyncio.TimeoutError，被下面统一捕获为任务失败，不会让一次挂死的调用
拖垂整条任务车道。
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from src.pipeline.paths import STATE_DIR, write_json_atomic

logger = logging.getLogger(__name__)

JOBS_PATH = STATE_DIR / "webapp_jobs.json"

# 任务历史只保留最近这么多条——这个文件每次写都是整体重写，不设上限的话
# 会随使用无限膨胀。运行中/排队中的任务永远保留，只裁剪已结束的。
MAX_JOB_HISTORY = 200

# 墙钟上限。取值依据：PDF 实测 15-30 分钟（含索引与多次串行 LLM 调用），
# 给到 45 分钟留足余量；超出基本可以断定是卡死而不是慢。
TIMEOUTS = {
    "process_pdf": 45 * 60,
    "process_web": 15 * 60,
    "sync_memory": 30 * 60,
    "render_report": 5 * 60,
}

ACTIVE_STATUSES = ("queued", "running", "cancelling")

_queue: Optional[asyncio.Queue] = None
_state_lock: Optional[asyncio.Lock] = None

# 当前正在跑的任务——cancel_job() 需要拿到实际的 asyncio.Task 才能真正
# 中断一个"running"状态的任务（光改 JSON 里的状态字段并不会打断一个正在
# await 的协程）。同一时刻车道是单条串行的，所以只需要记一个，不需要
# 每个 job_id 一个 Task 的字典。
_running_job_id: Optional[str] = None
_running_task: Optional[asyncio.Task] = None
# 区分"我们自己主动取消了当前任务"和"整条 worker 被取消"（比如应用关闭）
# ——两者在 await 当前任务时都表现为 CancelledError，必须靠这个标记位
# 分辨：前者要吞掉异常继续跑下一个任务，后者要原样往上冒泡让 worker 停。
_job_cancel_requested = False


# ---- 状态文件 ----

def _load_jobs() -> dict:
    if not JOBS_PATH.exists():
        return {"jobs": []}
    try:
        with open(JOBS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("任务状态文件无法解析，按空状态重来: %s", JOBS_PATH)
        return {"jobs": []}
    data.setdefault("jobs", [])
    return data


def _save_jobs(data: dict) -> None:
    jobs = data.get("jobs", [])
    active = [j for j in jobs if j["status"] in ACTIVE_STATUSES]
    finished = [j for j in jobs if j["status"] not in ACTIVE_STATUSES]
    data["jobs"] = active + finished[-MAX_JOB_HISTORY:]
    write_json_atomic(JOBS_PATH, data)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


async def _update_job(job_id: str, **fields) -> None:
    async with _state_lock:
        data = _load_jobs()
        for job in data["jobs"]:
            if job["job_id"] == job_id:
                job.update(fields)
                break
        _save_jobs(data)


def list_jobs() -> list:
    """给 API 轮询用。最近创建的在前。"""
    jobs = _load_jobs()["jobs"]
    return sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)


# ---- 入队 ----

async def enqueue(kind: str, target: str, title: str = "", item_type: str = None) -> dict:
    """登记一个任务并放进车道。

    同一个 target 已经在排队或运行中时直接返回那一条，不重复入队——用户
    连点两下"加载"不该跑两遍，而重复跑同一个 item 会让两次调用同时改
    同一批 queue 条目。
    """
    async with _state_lock:
        data = _load_jobs()
        for job in data["jobs"]:
            if job["target"] == target and job["status"] in ACTIVE_STATUSES:
                return job

        job = {
            "job_id": str(uuid.uuid4()),
            "kind": kind,
            "target": target,
            "item_type": item_type,
            "title": title,
            "status": "queued",
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "error": None,
        }
        data["jobs"].append(job)
        _save_jobs(data)

    await _queue.put(job["job_id"])
    logger.info("任务入队 %s: %s (%s)", job["job_id"][:8], target, kind)
    return job


async def retry_job(job_id: str) -> dict:
    """把一个已结束的失败/中断任务重新入队。"""
    async with _state_lock:
        data = _load_jobs()
        job = next((j for j in data["jobs"] if j["job_id"] == job_id), None)
    if job is None:
        return {"ok": False, "error": f"任务不存在: {job_id}"}
    if job["status"] not in ("failed", "interrupted"):
        return {"ok": False, "error": f"任务当前状态为 {job['status']}，不是失败/中断，无需重试"}

    new_job = await enqueue(job["kind"], job["target"], title=job.get("title", ""),
                             item_type=job.get("item_type"))
    return {"ok": True, "job": new_job}


async def cancel_job(job_id: str) -> dict:
    """取消一个排队中或正在运行的任务。

    排队中：直接标记为 cancelled——job_id 仍然留在 asyncio.Queue 里，
    但 run_forever() 在真正取出执行前会重新读一遍当前状态，发现不再是
    queued 就跳过，不会执行 _run_job()。

    运行中：调用 asyncio.Task.cancel()。_run_job() 内部各分支用
    asyncio.wait_for 包着实际调用，取消会转化成 CancelledError 从
    wait_for 抛出——run_forever() 单独捕获这个异常，标记为 cancelled
    而不是 failed。底层 pipeline_queue.json 里对应条目会停在
    in_progress，交给 select_processable() 的 reset_stale_in_progress
    自愈（和服务器重启中断是同一套恢复机制，不用在这里特殊处理）。"""
    async with _state_lock:
        data = _load_jobs()
        job = next((j for j in data["jobs"] if j["job_id"] == job_id), None)
        if job is None:
            return {"ok": False, "error": f"任务不存在: {job_id}"}
        if job["status"] not in ACTIVE_STATUSES:
            return {"ok": False, "error": f"任务当前状态为 {job['status']}，无法取消"}
        job["status"] = "cancelling" if job["status"] == "running" else "cancelled"
        if job["status"] == "cancelled":
            job["finished_at"] = _now()
            job["error"] = "用户取消"
        _save_jobs(data)

    if job_id == _running_job_id and _running_task is not None:
        global _job_cancel_requested
        _job_cancel_requested = True
        _running_task.cancel()

    return {"ok": True}


# ---- 各类任务的执行 ----

async def _run_job(job: dict) -> dict:
    kind, target = job["kind"], job["target"]

    if kind == "process_item":
        item_type = job.get("item_type")
        timeout_key = "process_pdf" if item_type == "pdf_arxiv" else "process_web"
        try:
            if item_type == "pdf_arxiv":
                from src.pipeline.process_pdf_queue import main_async as process_pdf_main_async
                await asyncio.wait_for(
                    process_pdf_main_async(limit=0, provider="openai", item_id=target),
                    timeout=TIMEOUTS[timeout_key],
                )
            else:
                from src.pipeline.process_web_queue import main_async as process_web_main_async
                await asyncio.wait_for(
                    process_web_main_async(limit=0, item_id=target),
                    timeout=TIMEOUTS[timeout_key],
                )
        except asyncio.TimeoutError:
            return {"error": f"处理 {target} 超时（>{TIMEOUTS[timeout_key]}s）"}
        except Exception as e:  # noqa: BLE001
            return {"error": f"处理 {target} 失败: {e}"}
        # process_pdf_queue/process_web_queue 的 process_item() 已经在内部
        # inline 调用了一次 ingest_source（见两者实现），这里不需要再补一次
        # sync_memory_ingest——与合并前 ai-research-pipeline 的两阶段设计
        # （处理完摘要落盘 -> 单独再 ingest）不同，是本次合并时的简化。
        return {"ok": True}

    if kind == "sync_memory":
        try:
            from src.pipeline.sync_memory_ingest import main_async as sync_memory_main_async
            await asyncio.wait_for(
                sync_memory_main_async(limit=0, provider="openai", item_id=None),
                timeout=TIMEOUTS["sync_memory"],
            )
        except asyncio.TimeoutError:
            return {"error": f"批量入库超时（>{TIMEOUTS['sync_memory']}s）"}
        except Exception as e:  # noqa: BLE001
            return {"error": f"批量入库失败: {e}"}
        return {"ok": True}

    if kind == "render_report":
        try:
            from src.pipeline.paths import OUTPUT_DIR
            from src.pipeline.render_report import render_report

            html_content = await asyncio.wait_for(
                asyncio.to_thread(render_report, target), timeout=TIMEOUTS["render_report"],
            )
            out_dir = OUTPUT_DIR / target
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "report.html").write_text(html_content, encoding="utf-8")
        except asyncio.TimeoutError:
            return {"error": f"生成报告超时（>{TIMEOUTS['render_report']}s）"}
        except Exception as e:  # noqa: BLE001
            return {"error": f"生成报告失败: {e}"}
        return {"ok": True}

    return {"error": f"未知任务类型: {kind}"}


# ---- worker ----

async def run_forever() -> None:
    """管线任务车道的常驻 worker。

    循环体整个包在 try/except 里：asyncio task 里逃出去的异常会被静默
    吞掉，worker 就此死掉而外部毫无察觉——之后所有任务都会永远停在
    queued。"""
    logger.info("管线任务 worker 已启动")
    while True:
        job_id = None
        global _running_job_id, _running_task, _job_cancel_requested
        try:
            job_id = await _queue.get()
            async with _state_lock:
                data = _load_jobs()
                job = next((j for j in data["jobs"] if j["job_id"] == job_id), None)
            if job is None:
                continue
            # 排队期间被 cancel_job() 取消——状态已经不是 queued 了，
            # 直接跳过，不真正执行。
            if job["status"] != "queued":
                logger.info("任务已被取消，跳过 %s: %s", job_id[:8], job.get("target"))
                continue

            await _update_job(job_id, status="running", started_at=_now())
            logger.info("任务开始 %s: %s", job_id[:8], job["target"])

            _running_job_id = job_id
            _running_task = asyncio.create_task(_run_job(job))
            try:
                outcome = await _running_task
            except asyncio.CancelledError:
                if _job_cancel_requested:
                    # 我们自己发起的取消：吞掉异常，标记状态，继续跑下一
                    # 个任务，不能 raise——那样会连累整条 worker 停摆。
                    _job_cancel_requested = False
                    await _update_job(job_id, status="cancelled", finished_at=_now(), error="用户取消")
                    logger.info("任务已取消 %s: %s", job_id[:8], job["target"])
                    continue
                raise  # 不是我们发起的取消（比如应用关闭），原样往上冒泡
            finally:
                _running_job_id = None
                _running_task = None

            if "error" in outcome:
                await _update_job(job_id, status="failed", finished_at=_now(), error=outcome["error"])
                logger.warning("任务失败 %s: %s", job_id[:8], outcome["error"])
            else:
                await _update_job(job_id, status="done", finished_at=_now())
                logger.info("任务完成 %s: %s", job_id[:8], job["target"])
        except asyncio.CancelledError:
            logger.info("管线任务 worker 停止")
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("任务执行出错，worker 继续运行")
            if job_id:
                try:
                    await _update_job(job_id, status="failed", finished_at=_now(), error=f"worker 异常: {e}")
                except Exception:  # noqa: BLE001
                    pass


async def recover_on_startup() -> None:
    """把上次进程被杀时留下的任务收拾干净。

    留在 running 的任务对应的调用早就随父进程一起没了，标成 interrupted；
    留在 queued 的重新入队继续跑。

    不需要在这里重置 queue 条目的 in_progress 状态——process_pdf_queue.py/
    process_web_queue.py 每次启动都会调 select_processable，它内部的
    reset_stale_in_progress 会把遗留的 in_progress 打回 pending。"""
    async with _state_lock:
        data = _load_jobs()
        requeue = []
        for job in data["jobs"]:
            if job["status"] == "running":
                job["status"] = "interrupted"
                job["finished_at"] = _now()
                job["error"] = "服务重启，任务被中断"
            elif job["status"] == "cancelling":
                # 取消请求发出后、worker 还没来得及处理 CancelledError
                # 就被重启打断——直接按取消收尾，不重新入队。
                job["status"] = "cancelled"
                job["finished_at"] = _now()
                job["error"] = "用户取消"
            elif job["status"] == "queued":
                requeue.append(job["job_id"])
        _save_jobs(data)

    for job_id in requeue:
        await _queue.put(job_id)
    if requeue:
        logger.info("重启后重新入队 %d 个任务", len(requeue))


def init() -> None:
    """在事件循环里创建队列与锁（asyncio 原语必须绑定到运行中的 loop，
    不能在 import 时建）。"""
    global _queue, _state_lock
    _queue = asyncio.Queue()
    _state_lock = asyncio.Lock()
