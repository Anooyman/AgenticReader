"""外部 LLM-Memory 简报加载的后台驱动——把「加载某个日期」从 HTTP 请求
里挪进 job_runner 车道，供 /memory 页的批量加载用。

所有对外部 webui 的一跳都走 src/memory/gateway.py 的 bridge_request /
brief_load / brief_load_progress；本文件只负责轮询节奏与 BriefLoadError
的文案，不再自己拼外部 URL——全仓唯一的地址读取点在 gateway。

## 为什么不直接在请求里转发

外部 webui 的 `/api/briefs/load` 注册现在走 `_reserve_job`，有自己的
per-registry 活跃上限了（`_MAX_ACTIVE_JOBS = 8`，server.py 的
`_BRIEF_LOAD_JOBS` + jobs.py；早先"完全没有并发上限"的说法随那边补闸门
已经过时）。但它依旧没有跨日期队列，而且是 thread-per-job——日期列表上
连点几行，8 个 job 会一起朝同一个 LLM 网关和 embedding 端点冲，更慢也更
爱互相撞车；同一个日期并发跑两遍还会写进重复记忆行（它那边的去重靠
`state["done"]` 标记，check-then-act 之间没有锁，两个 job 同时读到"没跑过"
就会都跑）。

所以这里改成**一天一个本地 job、过 job_runner 那条串行队列**，把外部并发
压成 1——cap=8 是那边自家的闸门，串行=1 是我们自己的第二道闸门，两者并不
重复。队列也顺带白拿已有的取消/重试/历史查询。

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
from typing import Any, Dict

import httpx

from src.memory import gateway

logger = logging.getLogger(__name__)

# 地址的唯一读取点在 gateway 桥侧；这里只是给日志行留个同名的别名。
LLM_MEMORY_URL = gateway.LLM_MEMORY_URL

# 轮询间隔。外部 job 自己也是靠这个接口被查询的，3s 足够，再快只是白耗连接。
_POLL_INTERVAL_S = 3.0
# 单次 HTTP 调用的超时。load/progress 都是即时返回的轻请求，读超时给 30s
# 已经留了很大余量——真正耗时的部分在后台线程里，不占这条连接。
# 只是超时对象，真正发请求的是 gateway.bridge_request。
_TIMEOUT = httpx.Timeout(15.0, read=30.0)


class BriefLoadError(RuntimeError):
    """外部服务不可达、拒绝了这个日期，或返回了预期外的形状。"""


def _flatten(body) -> str:
    """把错误响应（gateway 解析后的 body）压成一行文本，优先用
    detail/error/message 字段——键序与旧的 _detail_from 一致。"""
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
    try:
        status, payload = await gateway.brief_load([date], timeout=_TIMEOUT)
    except gateway.BridgeError as exc:
        # transport 级失败的文案由 gateway 逐字保住旧措辞，job_runner 的
        # "加载简报 X 失败: {e}" 外层包起来后与改前一致。
        raise BriefLoadError(str(exc.detail)) from exc

    if status >= 400:
        raise BriefLoadError(f"外部服务拒绝加载 {date}："
                             f"HTTP {status} {_flatten(payload)}")

    payload = payload or {}
    external_job_id = payload.get("job_id")
    if not isinstance(external_job_id, str) or not external_job_id:
        raise BriefLoadError(f"外部服务没有返回 job_id：{payload}")

    logger.info("简报加载已交给外部服务 %s: date=%s job=%s",
                LLM_MEMORY_URL, date, external_job_id[:8])

    while True:
        try:
            # 注：外层措辞沿用"查询 X 的加载进度失败（job=…）"，内层拼接
            # gateway BridgeError 的 detail（"webui 不可达…"整段）。旧版本这里
            # 拼的是原始异常文本，语义同类、job 账本可追，属收敛后的刻意
            # 口径；逐字保留旧措辞的承诺只在 502 映射处由测试锁死。
            status, job = await gateway.brief_load_progress(
                external_job_id, timeout=_TIMEOUT)
        except gateway.BridgeError as exc:
            raise BriefLoadError(
                f"查询 {date} 的加载进度失败（job={external_job_id[:8]}）："
                f"{exc.detail}") from exc

        if status >= 400:
            raise BriefLoadError(f"查询 {date} 的加载进度失败：HTTP "
                                 f"{status} {_flatten(job)}")

        job = job or {}
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
