"""外部 LLM-Memory 简报加载的后台驱动——把「加载某个日期」从 HTTP 请求
里挪进 job_runner 车道，供 /memory 页的批量加载用。

## 为什么不直接在请求里转发

外部 webui 的 `/api/briefs/load` 是 thread-per-job：没有队列，也没有并发
上限。那边的 `_MAX_ACTIVE_JOBS = 8` 只挂在 ingest/chat 两类任务上，brief
load 一个都没接——所以用户在日期列表上连点几行，就会同时开十几个 job，
朝同一个 LLM 网关和 embedding 端点一起冲，更慢也更爱互相撞车；同一个日期
被并发跑两遍还会写进重复的记忆行（它那边的去重靠 `state["done"]` 标记，
两个 job 同时读到"没跑过"就会都跑）。

这里把它改成**一天一个本地 job、过 job_runner 那条串行队列**，并发天然
被限制成 1，同时白拿队列已有的取消/重试/历史查询。

## 语义差异（有意保留）

- 外部 job 是"一次请求可以带多个日期，job 内部串行跑"；我们拆成一天一个
  job，代价是多几次 HTTP 往返，换来的是单个日期失败不影响别的日期、单个
  日期能单独取消/重试。
- **取消只停止本地跟踪**。外部那轮 load 没有停止端点（它只有 chat 的
  `/api/chat/stop`），所以取消之后它还会自己跑完，这个日期最终还是会被加载
  上——UI 上的状态会先变 cancelled，之后刷新日期时又显示成已加载。这是
  刻意写下来的行为，不是 bug。

协议保持原样：`POST /api/briefs/load {dates:[d]}` 立刻返回 `job_id`，
然后 `GET /api/briefs/load/progress/{job_id}` 一直问到 `done`。
"""
import asyncio
import logging
import os
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)

# 与 api/v1/llmmemory.py 同源：同一个外部服务，同一个环境变量，同一份默认值。
LLM_MEMORY_URL = os.environ.get("LLM_MEMORY_URL", "http://127.0.0.1:8765").rstrip("/")

# 轮询间隔。外部 job 自己也是靠这个接口被查询的，3s 足够，再快只是白耗连接。
_POLL_INTERVAL_S = 3.0
# 单次 HTTP 调用的超时。load/progress 都是即时返回的轻请求，读超时给 30s
# 已经留了很大余量——真正耗时的部分在后台线程里，不占这条连接。
_TIMEOUT = httpx.Timeout(15.0, read=30.0)


class BriefLoadError(RuntimeError):
    """外部服务不可达、拒绝了这个日期，或返回了预期外的形状。"""


def _detail_from(resp: httpx.Response) -> str:
    """把错误响应压成一行文本，优先用 JSON 里的 detail/error 字段。"""
    try:
        body = resp.json()
    except ValueError:
        return (resp.text or "")[:300]
    if isinstance(body, dict):
        for key in ("detail", "error", "message"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict) and isinstance(value.get("detail"), str):
                return value["detail"]
        return str(body)[:300]
    return str(body)[:300]


async def load_date(date: str) -> Dict[str, Any]:
    """请求外部服务加载一个日期的简报，并轮询到它自己结束。

    返回 `{"loaded": bool, "skipped": bool, "errors": [...]}`：
    loaded/skipped 来自它 job 里的同名字段——`loaded` 表示这天的条目真的
    写进去了，`skipped` 表示之前就已经在 state.done 里、这次什么都没做
    （重复点"加载"通常是这个结果，属于正常路径，不算失败）。

    调用方（job_runner._run_job）会被 asyncio.wait_for 掐总时长；这里的
    sleep 都是可取消的，取消会原样变成 CancelledError 抛出去，不需要额外
    的 cancel_check 协议。
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(f"{LLM_MEMORY_URL}/api/briefs/load",
                                     json={"dates": [date]})
        except httpx.HTTPError as exc:
            raise BriefLoadError(
                f"LLM-Memory webui 不可达（{LLM_MEMORY_URL}）：{exc}. "
                "请确认已运行: python scripts/webui/server.py --port 8765"
            ) from exc

        if resp.status_code >= 400:
            raise BriefLoadError(f"外部服务拒绝加载 {date}："
                                 f"HTTP {resp.status_code} {_detail_from(resp)}")

        payload = resp.json() or {}
        external_job_id = payload.get("job_id")
        if not isinstance(external_job_id, str) or not external_job_id:
            raise BriefLoadError(f"外部服务没有返回 job_id：{payload}")

        logger.info("简报加载已交给外部服务 %s: date=%s job=%s",
                    LLM_MEMORY_URL, date, external_job_id[:8])

        progress_url = f"{LLM_MEMORY_URL}/api/briefs/load/progress/{external_job_id}"
        while True:
            try:
                resp = await client.get(progress_url)
            except httpx.HTTPError as exc:
                raise BriefLoadError(
                    f"查询 {date} 的加载进度失败（job={external_job_id[:8]}）：{exc}"
                ) from exc

            if resp.status_code >= 400:
                raise BriefLoadError(f"查询 {date} 的加载进度失败：HTTP "
                                     f"{resp.status_code} {_detail_from(resp)}")

            job = resp.json() or {}
            if job.get("done"):
                loaded = bool(job.get("loaded"))
                errors = job.get("errors") or []
                if errors:
                    logger.warning("简报日期 %s 加载完成但有警告：%s", date, errors)
                return {
                    "loaded": loaded,
                    "skipped": bool(job.get("skipped")),
                    "errors": [str(e) for e in errors],
                }

            await asyncio.sleep(_POLL_INTERVAL_S)
